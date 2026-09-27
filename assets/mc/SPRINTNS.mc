#NEW VERSION, This Function Key File requires N1MM Logger V12.02.00 or newer
#REM, SPRINTNS Function key definitions 
#REM,   rev'ed by K8UT 26APR2012 
#EDITS REQUIRED, before using this file-----------------------------------------
#REM, Use this file as a set of baseline Messages when creating your own
#REM, non-ESM - no change required 
#REM, ESM - RUN F2 - remove the {ENTER} and first ! to avoid double-sending his callsign
#SPECIAL INSTRUCTIONS, ---------------------------------------------------------
#REM, Special QSY rule when RUNning - See contest rules
#REM, Due to QSY rule the RUN TU has QSY - the S&P TU has QRZ? 
#REM, In >File >Open contest exchange = 001 <name> <state>
#REM, non-ESM mode <Enter> logs the contact and clears the QSO Entry window
#REM, S&P F1 calls CQ and automatically places the program in RUN mode
#REM, Designed to work in either ESM or non-ESM mode
#REM, F2 F3 F4 F5 use "!" macro for his callsign
#REM, RST signal report is not required in the exchange for this contest
#ADVANCED FUNCTIONS, -----------------------------------------------------------
#REM, Due to QSY rule and 3 part exchange some stations avoid dupes in this contest
#REM, RUN F4 - F4 Wrk B4 Wipe QRZ?<comma>{TX} {CALL} WRK B4 DE {MYCALL} QRZ? {RX}{F12}
#REM, Due to QSY rule some stations like automatic switch from S&P to Run at end of S&P QSO
#REM, S&P F3 S&&P TU<comma>{TX}{ENTER}TU de {MYCALL} QRZ? {RX}{RUN}   
#RUN MESSAGES, Run Messages begin here -----------------------------------------
F1 Run CQ,{TX}{ENTER}cq NS {MYCALL} {MYCALL} CQ {RX}
F2 Run Exch,{TX}{ENTER}! de {MYCALL} {EXCH} {EXCH} {RX}
F3 Run TU,{TX}{ENTER}! TU QSY {RX}{S&P}
F4 {MYCALL},{TX} {MYCALL} {RX} 
F5 His Call,{TX} ! {RX}
F6 -,-
F7 My Exch,{TX}{ENTER}{EXCH} {EXCH} {RX}
F8 Agn?,{TX}{ENTER}agn? agn? {RX}
F9 Number?,{TX}{ENTER}nr? {RX}
F10 Name?,{TX}{ENTER}name? {RX}
F11 State?,{TX}{ENTER}st? {RX}
F12 Wipe,{WIPE}
#S&P MESSAGES, Search and Pounce Messages begin here ---------------------------
F1 S&&P CQ,{TX} cq NS de {mycall} {mycall} CQ {RX} 
F2 S&&P Exch,{TX}{ENTER}! {EXCH} {EXCH} {MYCALL} {RX}
F3 S&&P TU,{TX}{ENTER}! TU de {MYCALL} QRZ? {RX}{RUN}
F4 S&&P Call Him,{TX}{ENTER}! de {MYCALL} {MYCALL} {RX}
F5 His Call,{TX} ! {RX}
F6 {MYCALL},{TX} {MYCALL} {RX}
F7 My Exch,{TX}{ENTER}{EXCH} {EXCH} {RX}
F8 Agn?,{TX}{ENTER}agn? agn? {RX}
F9 Number?,{TX}{ENTER}nr? {RX}
F10 Name?,{TX}{ENTER}name? {RX}
F11 State?,{TX}{ENTER}st? {RX}
F12 Wipe,{WIPE}