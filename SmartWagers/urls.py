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
    #path("get_button_state_view/<str:side>/", views.get_button_state_view)
    #path("reports", views.Reports, name="reports-page"),
    #path("su_admin/<slug:slug>", views.SuperUser, name="su_admin")
]   
