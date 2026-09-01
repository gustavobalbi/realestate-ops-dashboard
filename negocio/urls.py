from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("vendas/nova/", views.venda_nova_view, name="venda_nova"),
    path("vendas/ativas/", views.vendas_ativas_view, name="vendas_ativas"),
    path("vendas/<int:venda_id>/distrato/", views.distrato_view, name="distrato"),
    path("assistente/", views.assistente_view, name="assistente"),
    path("api/unidades-disponiveis/", views.unidades_disponiveis_json, name="unidades_disponiveis_json"),
    path("api/clientes-busca/", views.clientes_busca_json, name="clientes_busca_json"),
]
