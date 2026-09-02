import datetime as dt

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import analytics, auth, services
from .forms import LoginForm, NovaVendaForm, PerguntaForm
from .models import Cliente, Empreendimento, FinanceiroMensal, Unidade, Venda
from .nl_assistant import AssistantError, responder
from .normalize import UNIDADE_INDISPONIVEL, norm_status_unidade, venda_esta_ativa


def login_view(request):
    if request.usuario is not None:
        return redirect("dashboard")

    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        usuario = auth.authenticate(form.cleaned_data["email"], form.cleaned_data["senha"])
        if usuario is None:
            messages.error(request, "E-mail ou senha inválidos.")
        else:
            auth.login(request, usuario)
            next_url = request.GET.get("next") or "dashboard"
            return redirect(next_url)
    return render(request, "negocio/login.html", {"form": form})


@require_POST
def logout_view(request):
    auth.logout(request)
    return redirect("login")


@auth.login_required
def dashboard_view(request):
    velocidades = analytics.velocidade_vendas()
    piores = velocidades[:3]
    riscos = analytics.risco_estouro_custo()
    riscos_positivos = analytics.em_estouro(riscos)
    duplicidade = analytics.clientes_duplicados()
    inconsistencias = analytics.inconsistencias_financeiro()

    context = {
        "velocidades": velocidades,
        "piores": piores,
        "riscos": riscos_positivos[:10],
        "duplicidade": duplicidade,
        "inconsistencias": inconsistencias[:15],
        "total_inconsistencias": len(inconsistencias),
        "total_financeiro": FinanceiroMensal.objects.count(),
    }
    return render(request, "negocio/dashboard.html", context)


@auth.login_required
def unidades_disponiveis_json(request):
    from django.http import JsonResponse

    emp_id = request.GET.get("empreendimento_id")
    qs = Unidade.objects.all()
    if emp_id:
        qs = qs.filter(empreendimento_id=emp_id)
    disponiveis = [
        u for u in qs if norm_status_unidade(u.status) not in UNIDADE_INDISPONIVEL
    ]
    data = [
        {
            "id": u.id,
            "label": f"{u.identificador} · {u.tipo} · {u.area_privativa_m2:.1f} m² · "
            f"R$ {u.valor_tabela:,.2f}",
            "valor_tabela": u.valor_tabela,
        }
        for u in disponiveis
    ]
    return JsonResponse({"unidades": data})


@auth.login_required
def clientes_busca_json(request):
    from django.http import JsonResponse

    termo = request.GET.get("q", "").strip()
    if len(termo) < 2:
        return JsonResponse({"clientes": []})
    qs = Cliente.objects.filter(nome__icontains=termo)[:15]
    data = [{"id": c.id, "label": f"{c.nome} · {c.cidade or '—'}"} for c in qs]
    return JsonResponse({"clientes": data})


@auth.login_required
def venda_nova_view(request):
    empreendimentos = Empreendimento.objects.order_by("nome")
    form = NovaVendaForm(request.POST or None, initial={"data_venda": dt.date.today()})

    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        cliente_novo = None
        if not cd["cliente_id"]:
            cliente_novo = {
                "nome": cd["cliente_novo_nome"],
                "email": cd["cliente_novo_email"],
                "cidade": cd["cliente_novo_cidade"],
                "uf": cd["cliente_novo_uf"],
                "perfil": cd["cliente_novo_perfil"],
            }
        try:
            venda = services.registrar_venda(
                unidade_id=cd["unidade_id"],
                cliente_id=cd["cliente_id"],
                cliente_novo=cliente_novo,
                valor_venda=cd["valor_venda"],
                forma_pagamento=cd["forma_pagamento"],
                data_venda=cd["data_venda"],
            )
        except services.RegraDeNegocioError as exc:
            messages.error(request, str(exc))
        except (Unidade.DoesNotExist, Cliente.DoesNotExist):
            messages.error(request, "Unidade ou cliente selecionado não existe mais.")
        else:
            messages.success(request, f"Venda #{venda.id} registrada com sucesso.")
            return redirect("venda_nova")

    return render(
        request,
        "negocio/venda_nova.html",
        {"form": form, "empreendimentos": empreendimentos},
    )


@auth.login_required
def vendas_ativas_view(request):
    termo = request.GET.get("q", "").strip()
    qs = Venda.objects.select_related("unidade", "unidade__empreendimento", "cliente").order_by(
        "-data_venda"
    )
    vendas_ativas = [v for v in qs if venda_esta_ativa(v.status_venda, v.data_distrato)]
    if termo:
        termo_lower = termo.lower()
        vendas_ativas = [
            v
            for v in vendas_ativas
            if termo_lower in v.cliente.nome.lower()
            or termo_lower in v.unidade.identificador.lower()
            or termo_lower in v.unidade.empreendimento.nome.lower()
        ]
    return render(
        request, "negocio/vendas_ativas.html", {"vendas": vendas_ativas[:200], "q": termo}
    )


@auth.login_required
@require_POST
def distrato_view(request, venda_id: int):
    try:
        venda = services.registrar_distrato(venda_id=venda_id)
    except services.RegraDeNegocioError as exc:
        messages.error(request, str(exc))
    except Venda.DoesNotExist:
        messages.error(request, "Venda não encontrada.")
    else:
        messages.success(
            request,
            f"Distrato da venda #{venda.id} registrado. Unidade {venda.unidade.identificador} "
            "voltou a ficar disponível.",
        )
    return redirect("vendas_ativas")


@auth.login_required
def assistente_view(request):
    form = PerguntaForm(request.POST or None)
    resultado = None
    if request.method == "POST" and form.is_valid():
        try:
            resultado = responder(form.cleaned_data["pergunta"])
        except AssistantError as exc:
            messages.error(request, str(exc))
    return render(request, "negocio/assistente.html", {"form": form, "resultado": resultado})
