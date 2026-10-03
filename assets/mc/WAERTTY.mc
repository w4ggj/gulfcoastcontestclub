#NEW VERSION, December 2022
#CONTEST SETUP: In the Sent Exchange box in the Contest Setup dialog window:
#                enter # or 001
#NOTE:   Consult the online manual for instructions on sending and receiving QTCs in this contest
#EDITS MAY BE REQUIRED FOR NON-ESM:
#     No changes required if you use ESM,
#      or if you use a mouse right-click or the Insert key or the ; key to send the Run exchange,
#      but if you do not use ESM and just want to press F2 to send the Run exchange,
#      then add ! to the Run F2 message before the exchange, as follows: 
#       F2 Run Exch,{TX}{ENTER} ! {SENTRST} {EXCH} {EXCH} ! {RX}
#ADVANCED FUNCTION: LOGTHENPOP
#     To use LOGTHENPOP, change Run F6 to 
#       F6 Next,{TX}{ENTER} ! {LOGTHENPOP}TU - NOW {F5}{F2}{RX}
#      and in the Configurer, Function Keys tab, set the "Next Call" key to F6
#QTCs
#     F10 can be used to ask whether the other station wants to exchange QTCs
#     F11 is the negative response
#     Positive responses come from the Ctrl+Z window (press Ctrl+Z once to receive, twice to send)
###################
#   RUN Messages
###################
#
F1 Run CQ,{TX}{ENTER} WAE {MYCALL} {MYCALL} CQ {RX}{CLEARRIT}
F2 Run Exch,{TX}{ENTER} {SENTRST} {EXCH} {EXCH} ! {RX}
F3 Run TU,{TX}{ENTER} TU {MYCALL} CQ {RX}{CLEARRIT}
F4 {MYCALL},{TX} {MYCALL} {RX}
F5 His Call,{TX} ! {RX}
F6 -, -
F7 My Exch,{TX}{ENTER} {EXCH} {EXCH} {RX}
F8 Agn?,{TX}{ENTER} agn agn {RX}
F9 Number?,{TX}{ENTER} nr agn nr {RX}
F10 QTCs?,{TX} do you want/need QTCs? {RX}
F11 Sri,{TX} sri no qtcs {RX}
F12 Wipe,{WIPE}
#
###################
#   S&P Messages
###################
# Note: "&" doubled displays one "&" in the button label
#
F1 S&&P CQ,{TX} WAE {mycall} {mycall} CQ {RX}
F2 S&&P Exch,{TX}{ENTER} {SENTRST} {EXCH} {EXCH} {RX}
F3 S&&P TU,{TX}{ENTER} TU {RX}
F4 S&&P Call Him,{TX}{ENTER} {MYCALL} {MYCALL} {RX}
F5 His Call,{TX} ! {RX}
F6 {MYCALL},{TX} {MYCALL} {RX}
F7 My Exch,{TX}{ENTER} {EXCH} {EXCH} {RX}
F8 Agn?,{TX}{ENTER} agn agn {RX}
F9 Number?,{TX}{ENTER} nr agn nr {RX}
F10 QTCs?,{TX} do you want/need QTCs? {RX}
F11 Sri,{TX} sri no qtcs {RX}
F12 Wipe,{WIPE}    
   