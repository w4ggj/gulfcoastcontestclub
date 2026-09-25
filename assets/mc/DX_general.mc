#NEW VERSION, December 2022
#EDITS MAY BE REQUIRED FOR NON-ESM:
#     No changes required if you use ESM,
#      or if you use a mouse right-click or the Insert key or the ; key to send the Run exchange,
#      but if you do not use ESM and just want to press F2 to send the Run exchange,
#      then add ! to the Run F2 message before the exchange, as follows: 
#       F2 Run Exch,{TX}{ENTER} ! {SENTRST} {SENTRST} ! {RX}
###################
#   RUN Messages
###################
#
F1 Run CQ,{TX}{ENTER} CQ {MYCALL} {MYCALL} CQ {RX}{CLEARRIT}
F2 Run Exch,{TX}{ENTER} {SENTRST} {SENTRST} ! {RX}
F3 Run TU,{TX}{ENTER} TU {MYCALL} CQ {RX}{CLEARRIT}
F4 {MYCALL},{TX} {MYCALL} {RX}
F5 His Call,{TX} ! {RX}
F6 -, -
F7 -, -
F8 Agn?,{TX}{ENTER} agn agn {RX}
F9 -, -
F10 -, -
F11 -, -
F12 Wipe,{WIPE}
#
###################
#   S&P Messages
###################
# Note: "&" doubled displays one "&" in the button label
#
F1 S&&P QRL?,{TX} QRL? {mycall} K {RX}
F2 S&&P Exch,{TX}{ENTER} {SENTRST} {SENTRST} {RX}
F3 S&&P TU,{TX}{ENTER} TU {RX}
F4 S&&P Call Him,{TX}{ENTER} {MYCALL} {MYCALL} {RX}
F5 His Call,{TX} ! {RX}
F6 {MYCALL},{TX} {MYCALL} {RX}
F7 -, -
F8 Agn?,{TX}{ENTER} agn agn {RX}
F9 -, -
F10 -, -
F11 -, -
F12 Wipe,{WIPE}       