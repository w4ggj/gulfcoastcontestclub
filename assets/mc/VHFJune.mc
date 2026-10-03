#CONTEST:  CQ WPX RTTY, last edit 2013-02-05
#NEW VERSION, This Function Key File requires N1MM Logger V1
#EDITS REQUIRED, before usingthis file---------------------
#REM, non-ESM - no change required
#REM, ESM - RUN F2 - remove the {ENTER} and first ! to avoid
#SPECIAL INSTRUCTIONS, -------------------------------------
#REM, non-ESM mode <Enter> logs the contact and clears the Q
#REM, S&P F1 calls CQ and automatically places the program i
#REM, Designed to work in either ESM or non-ESM mode
#REM, F2 F3 F4 F5 use "!" macro for his callsign
#REM, F2 F7 {SENTRST} defaults to 599 or allows manual entry
#ADVANCED FUNCTIONS, ---------------------------------------
#REM LOGTHENPOP, use the following line - replacing <comma>
#REM, RUN F4 Now...POP<comma>{TX}{ENTER}! {LOGTHENPOP} TU NO
#RUN MESSAGES, Run Messages begin here ---------------------
F1 Run CQ,{TX}{ENTER}cq cq 6m test {MYCALL} {MYCALL} CQ {RX}
F2 Run Exch,{TX}{ENTER}! {EXCH} {EXCH} ! {RX}
F3 Run TU, {TX}{ENTER}! TU de {MYCALL} QRZ? {RX}
F4 {MYCALL},{TX} {MYCALL} {RX}
F5 His Call,{TX} ! {RX}
F6 -, -
F7 My Exch,{TX}{ENTER} {EXCH} {EXCH} {RX}
F8 Agn?, {TX}{ENTER}agn? agn? {RX}
F9 Grid?,{TX}{ENTER}grid? {RX}
F10 ClearStack,{CLRSTACK}
F11 -, -
F12 Wipe, {WIPE}
#S&P MESSAGES, Search and Pounce Messages begin here -------
F1 S&&P CQ,{TX} cq 6m test de {mycall} {mycall} CQ {RX}
F2 S&&P Exch,{TX}{ENTER}! {EXCH} {EXCH} {MYCALL} {RX}
F3 S&&P TU,{TX}{ENTER}! TU de {MYCALL} {RX}
F4 S&&P Call Him,{TX}{ENTER}! de {MYCALL} {MYCALL} {RX}
F5 His Call,{TX} ! {RX}
F6 {MYCALL},{TX} {MYCALL} {RX}
F7 My Exch,{TX}{ENTER}{SENTRST} {EXCH} {EXCH} {RX}
F8 Agn?,{TX}{ENTER}agn? agn? {RX}
F9 Grid?,{TX}{ENTER}grid? {RX}
F10 -, -
F11 -, -
F12 Wipe, {WIPE}
