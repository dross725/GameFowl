from .models import Wagers
from .models import Totals
from .models import Settings
from .services import get_fightnum
import random
from datetime import datetime


def trends ():
    fight_num = get_fightnum()
    return ()





# def payout_calculator():
#     global total_bet
#     global meron_total_bet
#     global wala_total_bet
#     global coms
#     meron_payout = 0 
#     wala_payout = 0

#     if total_bet > 50000:
#         if meron_total_bet > 20000:
#             meron_payout = total_bet / meron_total_bet
#             meron_payout = meron_payout - (meron_payout * coms)
#             meron_payout = format(meron_payout * 100, '.2f')

#         if wala_total_bet > 20000:
#             wala_payout = total_bet / wala_total_bet
#             wala_payout = wala_payout - (wala_payout * coms)
#             wala_payout = format(wala_payout * 100, '.2f')

#     return (meron_payout, wala_payout)
    