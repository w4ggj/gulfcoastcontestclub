#NEW VERSION, December 2022
#CONTEST SETUP: In the Sent Exchange box in the Contest Setup dialog window:
#                enter # (or 001) your name and your state/province/country code
#                 as in:   001 TOM CT
#EDITS MAY BE REQUIRED FOR NON-ESM:
#     No changes required if you use ESM,
#      or a mouse right-click or the Insert key or the ; key to send the Run exchange,
#      but if you do not use ESM and just want to press F2 to send the Run exchange,
#      then add ! to the Run F2 message before the exchange, as follows: 
#       F2 Run Exch,{TX}{ENTER} ! {MYCALL} # {EXCH} {RX}
###################
#   RUN Messages
###################
#
F1 Run CQ,{TX}{ENTER} NA {MYCALL} {MYCALL} CQ {RX}
F2 Run Exch,{TX}{ENTER} {MYCALL} # {EXCH} {RX}
F3 Run TU,{TX}{ENTER} TU {LOG}{RX}
F4 {MYCALL},{TX} {MYCALL} {RX}
F5 His Call,{TX} ! {RX}
F6 -, -
F7 My Exch,{TX}{ENTER} # {EXCH} {RX}
F8 Agn?,{TX}{ENTER} agn agn {RX}
F9 Nr?,{TX}{ENTER} nr agn nr {RX}
F10 Name?,{TX}{ENTER} name agn name {RX}
F11 State?,{TX}{ENTER} state agn state {RX}
F12 Wipe,{WIPE}
#
###################
#   S&P Messages
###################
# Note: "&" doubled displays one "&" in the button label
#
F1 S&&P CQ,{TX} NA {mycall} {mycall} CQ {RX}
F2 S&&P Exch,{TX}{ENTER} ! # {EXCH} {MYCALL} {RX}
F3 S&&P TU,{TX}{ENTER} TU {RX}
F4 S&&P Call Him,{TX}{ENTER} {MYCALL} {MYCALL} {RX}
F5 His Call,{TX} ! {RX}
F6 {MYCALL},{TX} {MYCALL} {RX}
F7 My Exch,{TX}{ENTER} # {EXCH} {RX}
F8 Agn?,{TX}{ENTER} agn agn {RX}
F9 Nr?,{TX}{ENTER} nr agn nr {RX}
F10 Name?,{TX}{ENTER} name agn name {RX}
F11 State?,{TX}{ENTER} state agn state {RX}
F12 Wipe,{WIPE}       