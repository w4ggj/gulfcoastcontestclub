#NEW VERSION, December 2022
#CONTEST SETUP: In the Sent Exchange box in the Contest Setup dialog window:
#                W/VE stations enter your state/province two-letter code
#                DX stations enter # or 001
#EDITS MAY BE REQUIRED FOR NON-ESM:
#     No changes required if you use ESM,
#      or a mouse right-click or the Insert key or the ; key to send the Run exchange,
#      but if you do not use ESM and just want to press F2 to send the Run exchange,
#      then add ! to the Run F2 message before the exchange, as follows: 
#       F2 Run Exch,{TX}{ENTER} ! {SENTRST} {EXCH} {EXCH} ! {RX}
#ADVANCED FUNCTION: LOGTHENPOP
#     To use LOGTHENPOP, change Run F11 to 
#       F11 Next,{TX}{ENTER} ! {LOGTHENPOP}TU - NOW {F5}{F2}{RX}
#      and in the Configurer, Function Keys tab, set the "Next Call" key to F11
###################
#   RUN Messages
###################
#
F1 Run CQ,{TX}{ENTER} RU {MYCALL} {MYCALL} CQ {RX}{CLEARRIT}
F2 Run Exch,{TX}{ENTER} {SENTRST} {EXCH} {EXCH} ! {RX}
F3 Run TU,{TX}{ENTER} TU {MYCALL} CQ {RX}{CLEARRIT}
F4 {MYCALL},{TX} {MYCALL} {RX}
F5 His Call,{TX} ! {RX}
F6 -, -
F7 My Exch,{TX}{ENTER} {EXCH} {EXCH} {RX}
F8 Agn?,{TX}{ENTER} agn agn {RX}
F9 Number?,{TX}{ENTER} nr agn nr agn {RX}
F10 State?,{TX}{ENTER} state agn state {RX}
F11 -, -
F12 Wipe,{WIPE}
#
###################
#   S&P Messages
###################
# Note: "&" doubled displays one "&" in the button label
#
F1 S&&P CQ,{TX} RU {mycall} {mycall} CQ {RX}
F2 S&&P Exch,{TX}{ENTER} {SENTRST} {EXCH} {EXCH} {RX}
F3 S&&P TU,{TX}{ENTER} TU {RX}
F4 S&&P Call Him,{TX}{ENTER} {MYCALL} {MYCALL} {RX}
F5 His Call,{TX} ! {RX}
F6 {MYCALL},{TX} {MYCALL} {RX}
F7 My Exch,{TX}{ENTER} {EXCH} {EXCH} {RX}
F8 Agn?,{TX}{ENTER} agn agn {RX}
F9 Number?,{TX}{ENTER} nr agn nr agn {RX}
F10 State?,{TX}{ENTER} state agn state {RX}
F11 -, -
F12 Wipe,{WIPE}       