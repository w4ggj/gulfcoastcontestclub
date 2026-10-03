#
# Digital Function Key File
#
# Edits may be necessary before using this file
#  In some contests - replace F1 expression CQ "TEST" with contest acronym
#    For example: WPX IOTA BARTG SPRINT    
#  Replace F6 and F9-11 Spare,  with contest exchange expressions
#    For example - Number? State? Zone?  
#    ESM - no other changes required 
#    non-ESM - RUN F2 - add ! after the {ENTER} to send his call
#
# S&P F1 calls CQ and automatically places the program in RUN mode
# F2 F3 F4 F5 use "!" macro for his callsign
# F2 F7 {SENTRST} will default to 599 or allows manual entry of sig report
#
###################
#   RUN Messages
###################
#
F1 Run CQ,{TX}{ENTER} TEST {MYCALL} {MYCALL} CQ {RX}{CLEARRIT}
F2 Run Exch,{TX}{ENTER} {SENTRST} {EXCH} {EXCH} ! {RX}
F3 Run TU,{TX}{ENTER} TU {MYCALL} CQ {RX}{CLEARRIT}
F4 {MYCALL},{TX} {MYCALL} {RX}
F5 His Call,{TX} ! {RX}
F6 Spare,
F7 My Exch,{TX}{ENTER} {SENTRST} {EXCH} {EXCH} {RX}
F8 Agn?,{TX}{ENTER} agn agn {RX}
F9 Spare,
F10 Spare,
F11 Spare,
F12 Wipe,{WIPE}
#
###################
#   S&P Messages
###################
# Note: "&" doubled displays one "&" in the button label
#
F1 S&&P CQ,{TX} TEST {MYCALL} {MYCALL} CQ {RX}
F2 S&&P Exch,{TX}{ENTER} {SENTRST} {EXCH} {EXCH} {RX}
F3 S&&P TU,{TX}{ENTER} TU {RX}
F4 S&&P Call Him,{TX}{ENTER} {MYCALL} {MYCALL} {RX}
F5 His Call,{TX} ! {RX}
F6 {MYCALL},{TX} {MYCALL} {RX}
F7 My Exch,{TX}{ENTER} {EXCH} {EXCH} {RX}
F8 Agn?,{TX}{ENTER} agn agn {RX}
F9 Spare,
F10 Spare,
F11 Spare,
F12 Wipe,{WIPE}
