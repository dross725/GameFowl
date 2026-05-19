from django.shortcuts import render, redirect
from django.urls import reverse
from django.http import JsonResponse, HttpResponseForbidden
from . import services as services
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.contrib.auth.decorators import login_required
from .models import SessionLog
from django.contrib.auth.views import LoginView
from django.contrib.auth.views import LogoutView
from django.utils.timezone import now

debug = False

# views.py
class LogoutViaPost(LogoutView):
    def post(self, request, *args, **kwargs):
        session = SessionLog.objects.filter(
            user=request.user,
            logout_time__isnull=True
        ).order_by('-login_time').first()
        
        
        if session:
            session.logout_time = now()
            session.save()

        return super().post(request, *args, **kwargs)


class RoleBasedLoginView(LoginView):
    def form_valid(self, form):
        response = super().form_valid(form)
        SessionLog.objects.create(user=self.request.user, login_time=now())
        return response

    def get_success_url(self):
        user = self.request.user
        groups = user.groups.values_list('name', flat=True)

        if 'admin' in groups:
            return reverse('admin-page') 
        elif 'teller' in groups:
            return reverse ('user-page') 
        elif 'display' in groups:
            return reverse ('index') 
        else:
            return '/unauthorized/'

def group_required(group_name):
    def decorator(view_func):
        @login_required
        def _wrapped_view(request, *args, **kwargs):
            if request.user.groups.filter(name=group_name).exists():
                return view_func(request, *args, **kwargs)
            return HttpResponseForbidden("You don't have access to this page.")
        return _wrapped_view
    return decorator

def get_teller_information(request):
    user = request.user
    username = user.username
    full_name = f"{user.first_name} {user.last_name}"
    email = user.email

    # Example: log it
    print(f"User {username} accessed this page.")

def get_button_state_view (request):
    mstate, wstate = services.get_control_status()
    return JsonResponse({"mstate": mstate, "wstate": wstate})

def get_fight_results_view (request):
    results = services.get_fight_results('fightnum', 'side', 'odds')
    return JsonResponse(list(results) , safe=False)    

def get_fight_status_view (request): 
    overall_status, meron_status, wala_status, fightnum  = services.get_fight_status()
    return JsonResponse({"overall_status": overall_status, "meron_status": meron_status, "wala_status": wala_status, "fightnum": fightnum})

def get_pot_values (request):
    m_total_pot, m_payout, w_total_pot, w_payout, total_pot, fight_num = services.get_Totals()
    return JsonResponse({"M_total_bet" : m_total_pot, "M_payout": m_payout, "W_total_bet": w_total_pot, "W_payout": w_payout, "Total_pot": total_pot, "fight_num": fight_num})

# Create your views here.
@group_required('display')
def index(request):
    meron_total, meron_payout, wala_total, wala_payout, total_bet, fightnum = services.get_Totals() 

    return render( request, 'SmartWagers/index.html', {
        'M_total_bet' : format(int(meron_total), ','),
        'M_payout' : meron_payout,
        'W_total_bet' : format(int(wala_total), ','),
        'W_payout' : wala_payout
    })

def SuperUser(request):
    return None

def Reports(request):
    return None

@group_required('admin')
def Main_admin(request):
    #initialize
    meron_total, meron_payout, wala_total, wala_payout, total_bet, fightnum = services.get_Totals() 
    current_fn = services.get_fightnum()

    print ("USER: " +str(request.user))
    
    if request.method == 'POST':
        wager = int(request.POST.get('wager_value', 0))
        wager_id = request.POST.get('wager_id', None)

        services.add_wager(wager, wager_id, current_fn)
        meron_total, meron_payout, wala_total, wala_payout, total_bet , fightnum = services.get_Totals() 

        # Notify WebSocket about the new bet
        channel_layer = get_channel_layer()
        #print ('channel')
        if channel_layer == None:
            print ("Channel Layer is None")
        else:
            async_to_sync(channel_layer.group_send)(
                "bet_updates", 
                {
                    'type': 'send_data', 
                    'action': 'update'
                }
            )
        
        print ("USER: " +str(request.user))
        if debug == True:
            print ('\n=================================')
            print ('mtotal ' +str(format(int(meron_total), ',')))
            print ('wtotal ' +str(format(int(wala_total), ',')))
            print ('mpayout ' +str(meron_payout)) 
            print ('wpayout ' +str(wala_payout))

        return redirect ('admin-page')

    return render( request, 'SmartWagers/administrator.html', {
        'M_total_bet' : format(int(meron_total), ','),
        'M_payout' : meron_payout,
        'W_total_bet' : format(int(wala_total), ','),
        'W_payout' : wala_payout
    })

   
@group_required('teller')
def Teller(request):
    #initialize
    meron_total, meron_payout, wala_total, wala_payout, total_bet , fightnum= services.get_Totals() 
    #comm = services.get_comm_val()
    current_fn = services.get_fightnum()

    if request.method == 'POST':
        wager = int(request.POST.get('wager_value', 0))
        wager_id = request.POST.get('wager_id', None)

        services.add_wager(wager, wager_id, current_fn)
        meron_total, meron_payout, wala_total, wala_payout, total_bet, fightnum= services.get_Totals() 

        # Notify WebSocket about the new bet
        channel_layer = get_channel_layer()
        #print ('channel')
        if channel_layer == None:
            print ("Channel Layer is None")
        else:
            async_to_sync(channel_layer.group_send)(
                "bet_updates", 
                {
                    'type': 'send_data', 
                    'action': 'update'
                }
            )
        
        if debug == True:
            print ('\n=================================')
            print ('mtotal ' +str(format(int(meron_total), ',')))
            print ('wtotal ' +str(format(int(wala_total), ',')))
            print ('mpayout ' +str(meron_payout)) 
            print ('wpayout ' +str(wala_payout))

        return redirect ('user-page')

    return render( request, 'SmartWagers/user.html', {
        'M_total_bet' : format(int(meron_total), ','),
        'M_payout' : meron_payout,
        'W_total_bet' : format(int(wala_total), ','),
        'W_payout' : wala_payout
         })
