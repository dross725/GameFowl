from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth import views as auth_views
from django.urls import path
from . import views

urlpatterns = [
    path('login', views.RoleBasedLoginView.as_view(template_name='SmartWagers/login.html'), name='login'),
    path('logout', views.LogoutViaPost.as_view(next_page='/login'), name='logout'),
    path("", views.index, name="index"),
    path("index", views.index, name="index"),
    path("administrator", views.Main_admin, name="admin-page"), #admin/<admin-name>
    path("user", views.Teller, name="user-page"),
    path("get_button_state_view/", views.get_button_state_view, name="get-button-state"),
    path("get_fight_status_view/", views.get_fight_status_view, name="get-fight-status"),
    path("get_pot_values/", views.get_pot_values, name="get-pot-values"),
    path("get_fight_results_view/", views.get_fight_results_view, name="get-fight-results"),
    path("reprint_wager/", views.reprint_wager, name="reprint-wager"),
    path("get_teller_balance/", views.get_teller_balance, name="get-teller-balance"),
    path("get_teller_fight_totals/", views.get_teller_fight_totals, name="get-teller-fight-totals"),
    path("get_pending_payouts/", views.get_pending_payouts, name="get-pending-payouts"),
    path("teller_transaction/", views.teller_transaction, name="teller-transaction"),
    path("reports/", views.teller_report, name="teller-report"),
    path("administrator/tellers/", views.admin_tellers, name="admin-tellers"),
    path("administrator/teller-txn/", views.admin_teller_txn, name="admin-teller-txn"),
    path("administrator/mark-received/", views.admin_mark_received, name="admin-mark-received"),
    path("administrator/start-event/", views.start_event_view, name="admin-start-event"),
    path("administrator/end-event/", views.end_event_view, name="admin-end-event"),
    path("administrator/event-report/", views.admin_event_report, name="admin-event-report"),
    path("administrator/claim-old-ticket/", views.admin_claim_old_ticket, name="admin-claim-old-ticket"),
    path("administrator/teller-transactions/", views.admin_teller_transactions, name="admin-teller-transactions"),
    path("administrator/commission/", views.admin_commission, name="admin-commission"),
    path("administrator/settings/", views.admin_settings, name="admin-settings"),
    path("administrator/teller-alerts/", views.admin_teller_alerts, name="admin-teller-alerts"),
    path("administrator/teller-online-toggle/", views.toggle_teller_online, name="admin-teller-online-toggle"),
    #path("get_button_state_view/<str:side>/", views.get_button_state_view)
    #path("reports", views.Reports, name="reports-page"),
    #path("su_admin/<slug:slug>", views.SuperUser, name="su_admin")
]   
