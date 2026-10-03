#NEW VERSION, This Function Key File requires N1MM Logger V12.02.00 or newer 
#EDITS REQUIRED, before using this file-----------------------------------------
#REM, non-ESM - no change required 
#REM, ESM - RUN F2 - remove the {ENTER} and first ! to avoid double-sending his callsign
#SPECIAL INSTRUCTIONS, ---------------------------------------------------------
#REM, non-ESM mode <Enter> logs the contact and clears the QSO Entry window
#REM, S&P F1 calls CQ and automatically places the program in RUN mode
#REM, Designed to work in either ESM or non-ESM mode
#REM, F2 F3 F4 F5 use "!" macro for his callsign
#REM, F2 F7 {SENTRST} defaults to 599 or allows manual entry of sig report
#ADVANCED FUNCTIONS, -----------------------------------------------------------
#REM LOGTHENPOP, use the following line - replacing <comma> 
#REM, RUN F4 Now...POP<comma>{TX}{ENTER}! {LOGTHENPOP} TU NOW...  {F5}{F2}{RX} 
#RUN MESSAGES, Run Messages begin here -----------------------------------------
F1 Run CQ,{TX}{ENTER}cq cq DRCG {MYCALL} {MYCALL} CQ {RX}
F2 Run Exch,{TX}{ENTER}! {SENTRST} {EXCH} {EXCH} ! {RX}
F3 Run TU, {TX}{ENTER}! TU de {MYCALL} QRZ? {RX}
F4 {MYCALL},{TX} {MYCALL} {RX} 
F5 His Call,{TX} ! {RX}
F6 -, -
F7 My Exch,{TX}{ENTER}{SENTRST} {EXCH} {EXCH} {RX}
F8 Agn?, {TX}{ENTER}agn? agn? {RX}
F9 Number?,{TX}{ENTER}number? {RX}
F10 Call?,{TX}{ENTER}call? {RX}
F11 -, -
F12 Wipe, {WIPE}
#S&P MESSAGES, Search and Pounce Messages begin here ---------------------------
F1 S&&P CQ,{TX} cq DRCG de {mycall} {mycall} CQ {RX} 
F2 S&&P Exch,{TX}{ENTER}! {SENTRST} {EXCH} {EXCH} {MYCALL} {RX}
F3 S&&P TU,{TX}{ENTER}! TU de {MYCALL} {RX}
F4 S&&P Call Him,{TX}{ENTER}! de {MYCALL} {MYCALL} {RX}
F5 His Call,{TX} ! {RX}
F6 {MYCALL},{TX} {MYCALL} {RX}
F7 My Exch,{TX}{ENTER}{SENTRST} {EXCH} {EXCH} {RX}
F8 Agn?,{TX}{ENTER}agn? agn? {RX}
F9 Number?,{TX}{ENTER}number? {RX}
F10 Call?,{TX}{ENTER}call? {RX}
F11 -,-
F12 Wipe, {WIPE}
