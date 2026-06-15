from django.urls import path
from . import views

urlpatterns = [
    path('', views.bank_root, name='bank_root'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('switch-account/', views.switch_account, name='switch_account'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('transactions/', views.transactions_list, name='transactions'),
    path('transactions/<str:reference>/bordereau/', views.download_transaction_slip, name='download_slip'),
    path('virement/', views.transfer, name='transfer'),
    path('beneficiaires/', views.beneficiaries, name='beneficiaries'),
    path('beneficiaires/<int:pk>/supprimer/', views.delete_beneficiary, name='delete_beneficiary'),
    path('rib/', views.download_rib, name='download_rib'),
    path('releve/', views.download_statement, name='download_statement'),
    path('notifications/', views.notifications_view, name='notifications'),
    path('securite/', views.change_password, name='change_password'),
    path('dismiss-block-modal/', views.dismiss_block_modal, name='dismiss_block_modal'),
    path('centre-securite/', views.security_center, name='security_center'),
    path('centre-securite/<str:reference>/annuler/', views.security_center_reject, name='security_center_reject'),
]
