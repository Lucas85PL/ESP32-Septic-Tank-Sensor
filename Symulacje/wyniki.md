# Wyniki symulacji (wygenerowane przez run_all.py)

PASS=75, FAIL=0

| ID | Test | Wynik | Szczegoly |
|---|---|---|---|
| A1 | czysty pomiar -> OK ~60 | PASS | OK 59.98 |
| A2 | % cykli bez poprawnego wyniku vs sigma szumu [cm] | info | s=0.5:0%, s=1.5:0%, s=3.0:0%, s=5.0:8%, s=8.0:23%, s=12.0:42% |
| A2 | sigma<=3 cm (rozsadne zmarszczki) -> <=2% cykli stracone | PASS |  |
| A3 | 50% timeoutow -> nadal OK | PASS | OK |
| A4 | 20% prawdziwych + 80% losowych (ref znany) -> >=70% poprawnych | PASS | 100% |
| A5 | wywoz 30 -> 160: 1. cykl czeka na potwierdzenie, 2. zgodny cykl przyjmuje | PASS | REJECTED_JUMP -> OK 161.1 |
| A5b | wywoz po fizycznym resecie TX przyjety od razu | PASS | OK |
| A5c | kandydat na wywoz niepotwierdzony (kolejny cykl normalny) jest odrzucony i kasowany | PASS | OK 58.9 |
| A5d | dwa cykle niezgodne (160 potem 120) nie potwierdzaja wywozu | PASS | REJECTED_JUMP |
| A6 | jednorazowe stabilne echo 150 cm (prawda 60) jest ODRZUCONE | PASS | REJECTED_JUMP -1.0 |
| A6b | czujnik wyjety na >= 12 h (stale 150 cm) -> falszywy wywoz nadal mozliwy po 2 cyklach | info | REJECTED_JUMP -> OK |
| A7 | strefa martwa [scatter 10-24 + 30% timeout]: cykl w ktorym TX wysle 25.0 | info | 6. cykl = 36 h |
| A7 | strefa martwa [stabilne 22.0+-0.2]: cykl w ktorym TX wysle 25.0 | info | NIGDY |
| A7 | strefa martwa [same timeouty]: cykl w ktorym TX wysle 25.0 | info | NIGDY |
| A7 | strefa martwa [40% <25, 60% timeout]: cykl w ktorym TX wysle 25.0 | info | NIGDY |
| A7 | strefa martwa raportowana po 36 h, RX alarmuje po 25 h | info | raport po 36 h  [ZAAKCEPTOWANE: wywoz jest organizowany przy zblizaniu sie do pelnego] |
| A7b | stabilne echo <25 cm / same timeouty w strefie martwej: TX milczy | info | ZAAKCEPTOWANE (poziom <= 25 cm jest widoczny wczesniej jako ~25-30 cm) |
| A8 | po 'zimnym' starcie (ref 100, prawda 60): cykli do pierwszej wartosci | info | 5 |
| A9 | bootstrap, dwa rowne klastry (30/30) -> brak wyniku (nie zgaduje) | PASS | NO_VALID |
| A10 | bootstrap z dominujacym falszywym echem 25.4 NIE staje sie odniesieniem | PASS | NO_VALID -1.0 |
| A11 | bootstrap: klaster dokladnie 11 probek | info | NO_VALID |
| A11 | bootstrap: klaster dokladnie 12 probek | info | OK |
| A12 | skok 100->40 (poza oknem 15cm/d): sekwencja statusow | info | REJECTED_JUMP REJECTED_JUMP REJECTED_JUMP REJECTED_JUMP OK OK OK |
| B1 | zdrowy system: okres cyklu [h] / wybudzen / aktywnosc na wybudzenie [s] | info | 6.043 h / 120 / 156 s ; ~13.0 mAh/dobe (bez uspienia) |
| B1 | okres cyklu w granicach 6.0-6.1 h | PASS |  |
| B2 | RX wylaczony 5 dni: wybudzen/dobe, aktywnosc s/dobe, radio s/dobe | info | 5.2 wyb/d, 676 s/d (norma 624), radio 53 s/d (norma 3) => ~1.3x energii |
| B2 | awaria RX nie zwieksza zuzycia energii TX > 2x | PASS | 1.3x |
| B2c | przy dlugiej awarii RX <= 5 wybudzen na dobe | PASS | 5.2/dobe (4 regularne + jednorazowa seria ponowien) |
| B2 | powrot dostarczania po powrocie RX | info | 2.7 h |
| B2b | sekwencja wybudzen (C=regularny, R=ponowienie) w 1. dobie awarii RX | info | CRRRRRRCCC |
| B3 | p_loss=40%/kierunek, 30 dni | info | wybudzen=257 ack_ok=110 dostarczone_do_RX=197 ekran_ostrzezenia=0.0 h |
| B4 | po resecie w trakcie pomiaru nastepny cykl zwraca poprawna wartosc | PASS | t+85s val=84.8 prawda=84.7 |
| B4b | uszkodzony meta.bin: epoki w logu RX / rekordy / duplikaty (e,id) | info | 1 / 48 / 0 |
| B4b | po uszkodzeniu meta TX nadal dostarcza logi i nie zawiesza sie | PASS |  |
| B5 | najdluzsze pojedyncze wybudzenie [s] | info | RX off: 166, loss 70%: 191, loss 95%: 166, sensor ślepy: 158 |
| B5 | zadne wybudzenie nie dluzsze niz 5 min (TX nie wisi) | PASS | max 191s |
| B6 | dryf RC oscylatora RTC +-5% | info | okres rzeczywisty 5.7-6.3 h; elapsedSincePrevWake liczony z zadanego snu (blad okna <= 5%, pomijalny) |
| C1 | bez strat: 20 rekordow dostarczone, kolejnosc, brak duplikatow | PASS | wybudzen=1, czas=7.3s |
| C2 | p_loss=0.05: wszystkie rekordy dostarczone dokladnie raz | PASS | wybudzen do oproznienia=2, max czas flush=15.7s |
| C2 | p_loss=0.10: wszystkie rekordy dostarczone dokladnie raz | PASS | wybudzen do oproznienia=3, max czas flush=20.5s |
| C2 | p_loss=0.20: wszystkie rekordy dostarczone dokladnie raz | PASS | wybudzen do oproznienia=18, max czas flush=10.8s |
| C2 | p_loss=0.30: po 200 wybudzeniach dostarczono 100% rekordow (bez duplikatow: True) | info | TX zawsze zaczyna rekord od porcji 0 - przy ~18 porcjach/rekord szansa 'calosc w jednym wybudzeniu' maleje wykladniczo |
| C2 | p_loss=0.50: po 200 wybudzeniach dostarczono 70% rekordow (bez duplikatow: True) | info | TX zawsze zaczyna rekord od porcji 0 - przy ~18 porcjach/rekord szansa 'calosc w jednym wybudzeniu' maleje wykladniczo |
| C3 | tresc rekordow identyczna bajt w bajt (p_loss=0.15) | PASS |  |
| C4 | reboot RX w polowie rekordu -> rekord dostarczony od nowa | PASS | rekordow=3 |
| C5 | dysk RX pelny: wybudzen bez postepu, max czas flush | info | None, 1.2s |
| C5 | dysk RX pelny nie blokuje TX dluzej niz budzet | PASS |  |
| C5b | po zwolnieniu miejsca na RX nadrabia zaleglosci | PASS |  |
| C6 | po nowej epoce TX (id znow od 1) RX przyjmuje rekordy | PASS | 8/8 |
| C7 | RX bez NVS + TX ponownie wysyla wszystko: rekordow w pliku RX (duplikaty) | info | 8 |
| C8 | flush ograniczony budzetem czasu | PASS | 0.9s |
| C9 | RX zajety 0.5 s po pakiecie pomiaru: czas wysylki 1 rekordu / porcji wyslanych | info | 0.87s / 18 |
| C9 | opoznione ACK nie psuje dostarczenia | PASS |  |
| D1 | RX po wywozie (bez RESET): resety historii / ile z 20 kolejnych odczytow '-- dni' | info | 1 / 6 |
| D1 | po wywozie RX resetuje historie prognozy | PASS |  |
| D1b | po wywozie prognoza wraca do sensownej wartosci (<60 dni) najpozniej po 8 pomiarach | PASS | [(1, -1), (2, -1), (3, -1), (4, -1), (5, -1), (6, -1), (7, 21.5), (8, 20.5), (9, 21.5), (10, 20.0), (11, 19.5), (12, 19.5), (13, 20.0), (14, 19.0), (15, 18.0), (16, 18.0)] |
| D1c | po RESET: ekran 'oczekiwanie', brak starych danych, dioda wygaszona | PASS |  |
| D1d | pierwszy pakiet po RESET jest nowym startem (raw 155 -> 145 cm pokazane, historia 1 punkt) | PASS |  |
| D2 | prognoza 'Pelny za' (regresja): % '-- dni' / mediana bledu / p90 bledu / prawda w zakresie | info | 0% / 4% / 10% / 100% |
| D2 | prognoza: mediana bledu < 15%, p90 < 30%, '-- dni' < 5% | PASS |  |
| D3 | zbiornik wchodzi w strefe martwa (t_prawda<25 cm) -> pierwszy raport 25.0 | info | prawda<25 od 107 h, raport 25.0 od 139 h, ekran 'BRAK POMIARU' lacznie 11.2 h |
| D3 | alarm 'BRAK POMIARU' w strefie martwej [ZAAKCEPTOWANE - wywoz organizowany wczesniej] | info | 11.2 h |
| D4 | czujnik slepy od t=48 h: godzina alarmu / diody pomaranczowej / czerwonej | info | 67.47863833333334 / 67.47863833333334 / 92.4875677777778  (ostatni pomiar ok. 48 h) |
| D4 | ekran ostrzezenia pojawia sie 25-31 h po ostatnim pomiarze | PASS |  |
| D5 | RX bez pakietow, stan diody/ekranu po N dniach | info | 1d:green/measure, 2d:orange/warning, 10d:red/warning, 40d:red/warning, 49d:red/warning, 50d:red/warning, 51d:red/warning, 60d:red/warning, 100d:red/warning |
| D5 | po 50-100 dniach bez danych dioda zostaje czerwona (czas 64-bit) | PASS | 50d=red, 100d=red |
| D6 | wiek pomiaru po restarcie RX (prawdziwy 8.3 h) | info | 7.00 h  (czas bez zasilania nie jest liczony; zapis co 1 h) |
| D7 | NaN/Inf/ujemne/ogromne pakiety nie psuja stanu (wartosc ostatnia zachowana) | PASS | lastDistance=170.0 |
| D7 | pakiet 0.0 cm (dozwolony przez walidacje RX: raw>=0) -> wolne miejsce / procent | info | -10 cm / 0%  [TX nie wysyla <25] |
| D7 | RX nie sprawdza nadawcy: kazdy 10-bajtowy pakiet ESP-NOW na kanale 1 jest traktowany jako pomiar | info | brak filtra MAC/magic (ryzyko niskie, domowe srodowisko) |
| E1 | baseline 24 przebiegow x 60 dni (bledy z logu: slepota, echo 25.4, losowe) | info | widok DOBRY 94.7% | ALARM/nieaktualny 4.9% | BLEDNY 0.4% | sredni blad 5.9 cm | falszywe 'pelny' 1.4 h/przebieg |
| E1 | widok DOBRY >= 85% czasu w warunkach z usterkami | PASS | 94.7% |
| E1b | falszywy komunikat 'prawie pelny' (<=35 cm przy prawdzie >=55) < 2 h/przebieg | PASS | 1.4 h |
| E2 | bez usterek, 10 przebiegow | info | DOBRY 97.5% | alarm 1.8% | BLEDNY 0.7% | blad 6.43 cm |
| E2 | zdrowy czujnik: widok DOBRY >= 97% | PASS | 97.5% |
| E3 | temperatura powietrza -10 C (stala predkosc dzwieku 20 C) | info | srednie przesuniecie wskazania +0.8 cm przy ~100 cm |
| E3 | temperatura powietrza 0 C (stala predkosc dzwieku 20 C) | info | srednie przesuniecie wskazania +2.3 cm przy ~100 cm |
| E3 | temperatura powietrza 30 C (stala predkosc dzwieku 20 C) | info | srednie przesuniecie wskazania +6.9 cm przy ~100 cm |
| E4 | wymiana baterii TX (zimny start) podczas awarii RX | info | DOBRY 97.2% | alarm 2.8% | BLEDNY 0.1% |
| E5 | zbiornik dochodzi do 100% i jest oprozniany | info | DOBRY 97.8% | alarm 2.0% | BLEDNY 0.2% |
| E6 | czujnik wyjety na 36 h (stala 'sciana' 90 cm) | info | DOBRY 88.4% | alarm 4.7% | BLEDNY 6.8% |
| F1 | awaria RX 5 dni: energia wzgl. normy / wybudzen na dobe / powrot po wlaczeniu RX | info | 1.2x / 5.2 / 2.7 h; sekwencja 2 dob: CRRRRRRCCCCCCC |
| F1 | awaria RX: <= 2x energii normy | PASS | 1.2x |
| F1b | po powrocie RX dane docieraja w <= 6.5 h (najblizszy regularny cykl) | PASS | 2.7 h |
| F2 | wywoz: po ilu godzinach RX pokazuje 'pusty' - bez resetu TX / z fizycznym resetem TX | info | 7.9 h / 0.7 h |
| F2 | bez resetu TX wywoz widoczny w <= 13 h (2 cykle), z resetem TX w <= 1 h | PASS |  |
| F3 | p_loss=0.3/kierunek: wybudzen do dostarczenia 20 rekordow (z wznawianiem) | info | 55; dokladnie raz: True |
| F3 | przy 30% strat/kierunek 20 rekordow (~18 porcji) dociera w <= 80 wybudzeniach (bez wznawiania praktycznie nigdy) | PASS | 55 |
| F3 | p_loss=0.5/kierunek: wybudzen do dostarczenia 20 rekordow (z wznawianiem) | info | None; dokladnie raz: True |
| F4 | czujnik wyjety na 5 h (jeden cykl 150 cm) NIE ustawia 'pustego zbiornika' | PASS | 0 probek fałszywego 'pusty' |
| G6a | pierwszy pakiet z 14 punktami -> od razu prognoza zielona z regresji | PASS | (15, 15, False, 'green') |
| G6a | wartosc prognozy bliska prawdy (5 cm/dobe) | PASS | (15, 15, False, 'green') vs 15.0 |
| G6b | 1 punkt po wywozie -> prior 6 cm/dobe, pomaranczowy | PASS | (22, 22, False, 'orange') |
| G6b | 7 punktow / 36 h -> zielona (regresja) | PASS | (28, 29, False, 'green') |
| G6b | 6 punktow / 30 h -> jeszcze pomaranczowa (prior) | PASS | (19, 19, False, 'orange') |
| G6c | po RESET historia pusta i ekran 'waiting' | PASS |  |
| G6c | stary pakiet (seq <= odciecie) po RESET jest ignorowany | PASS |  |
| G6c | nowy seq: tylko punkty z seq > odciecia (1 punkt), reszta stara odrzucona | PASS | 1 pkt |
| G6d | inna epoka (TX po erase, seq od 1) jest przyjmowana mimo odciecia | PASS |  |
| G6e | skok > 50 cm w odebranej historii odcina starsze punkty | PASS | 2 pkt |
| G6f | po restarcie RX prognoza dostepna natychmiast (blob NVS) i zgodna z przed restartem | PASS | przed (15, 15, False, 'green') po (15, 15, False, 'green') |
| G6g | odciecie po RESET przezywa utrate zasilania RX | PASS | 0 pkt |
| G6h | punkt syntetyczny 25.0 (strefa martwa): prognoza 0 dni, nie psuje regresji | PASS | (0, 0, False, 'green') |
| G1 | po wywozie (RX RESET +1 h, TX reset +2 h), 12 przebiegow: godz. do 1. prognozy [mediana/max] STARY | NOWY | info | STARY 42/42 h | NOWY 0/0 h |
| G1 | godz. do prognozy 'zielonej' (z regresji) STARY | NOWY | info | STARY 42/42 h | NOWY 36/36 h |
| G1 | blad prognozy w 6 dniach po wywozie [mediana bledu | p90 | dostepnosc] STARY | NOWY | info | STARY 10% | 18% | 71%  ||  NOWY 8% | 22% | 100%  (orange: 9%, green: 9%, udzial pomaranczowej 25%) |
| G1 | stan ustalony przed wywozem (dni 4-8) [mediana bledu | p90 | dostepnosc] STARY | NOWY | info | STARY 9% | 16% | 100%  ||  NOWY 9% | 16% | 100% |
| G1 | NOWY: pierwsza prognoza (pomaranczowa) od razu po wywozie (<= 6 h od resetu TX) | PASS | max 0.2 h |
| G1 | NOWY: prognoza zielona (regresja) po <= 42 h od resetu TX | PASS | max 36 h |
| G1 | NOWY: stan ustalony nie gorszy od STAREGO (mediana bledu nie wieksza o > 3 pp) | PASS | 9% vs 9% |
| G1b | prior 6 cm/dobe: blad faz POMARANCZOWEJ [mediana ze znakiem (+ = za pozno) | max] i ZIELONEJ, wg prawdziwego tempa | info | 3 cm/d: -50% | 51% / zielona 0% ; 4 cm/d: -33% | 35% / zielona 0% ; 5 cm/d: -16% | 18% / zielona 0% ; 6 cm/d: 1% | 4% / zielona 1% ; 7 cm/d: 17% | 21% / zielona 1% ; 8 cm/d: 34% | 39% / zielona 1% |
| G1b | faza pomaranczowa: mediana bledu <= 55% dla tempa 3-8 cm/dobe (prior orientacyjny) | PASS |  |
| G1b | faza zielona: mediana bledu <= 15% niezaleznie od tempa | PASS |  |
| G2 | 3 krotkie zaniki RX (5-60 min) w dniach 5-10, 12 przebiegow: dostepnosc prognozy [srednia/min] | mediana bledu STARY | NOWY | info | STARY 37%/13% blad 11% | NOWY 100%/100% blad 10% |
| G2 | NOWY: po krotkich zanikach RX prognoza dostepna >= 97% czasu (STARY traci ok. 42 h po kazdym) | PASS | min 100% |
| G2 | NOWY: blad po zanikach nie gorszy niz bez nich (mediana <= 15%) | PASS | 10% |
| G3 | RX->TX (Twoj workflow), 30 h [STARY]: probek ze starymi danymi (prognoza <12 dni po resecie TX) / wyslane 25.0 przed resetem / godz. do 1. prognozy [med/max] / ekran 6 h po resecie [cm raw] | info | 0 / 0 / 42/42 h / 163 |
| G3 | RX->TX (Twoj workflow), 30 h [NOWY]: probek ze starymi danymi (prognoza <12 dni po resecie TX) / wyslane 25.0 przed resetem / godz. do 1. prognozy [med/max] / ekran 6 h po resecie [cm raw] | info | 0 / 0 / 0/0 h / 163 |
| G3 | RX->TX, 24 h [STARY]: probek ze starymi danymi (prognoza <12 dni po resecie TX) / wyslane 25.0 przed resetem / godz. do 1. prognozy [med/max] / ekran 6 h po resecie [cm raw] | info | 0 / 0 / 42/42 h / 164 |
| G3 | RX->TX, 24 h [NOWY]: probek ze starymi danymi (prognoza <12 dni po resecie TX) / wyslane 25.0 przed resetem / godz. do 1. prognozy [med/max] / ekran 6 h po resecie [cm raw] | info | 0 / 0 / 0/0 h / 164 |
| G3 | TX->RX (odwrotnie), 30 h [STARY]: probek ze starymi danymi (prognoza <12 dni po resecie TX) / wyslane 25.0 przed resetem / godz. do 1. prognozy [med/max] / ekran 6 h po resecie [cm raw] | info | 0 / 0 / 42/42 h / 163 |
| G3 | TX->RX (odwrotnie), 30 h [NOWY]: probek ze starymi danymi (prognoza <12 dni po resecie TX) / wyslane 25.0 przed resetem / godz. do 1. prognozy [med/max] / ekran 6 h po resecie [cm raw] | info | 0 / 0 / 0/0 h / 163 |
| G3 | bez RESET RX, 30 h [STARY]: probek ze starymi danymi (prognoza <12 dni po resecie TX) / wyslane 25.0 przed resetem / godz. do 1. prognozy [med/max] / ekran 6 h po resecie [cm raw] | info | 0 / 0 / 42/42 h / 163 |
| G3 | bez RESET RX, 30 h [NOWY]: probek ze starymi danymi (prognoza <12 dni po resecie TX) / wyslane 25.0 przed resetem / godz. do 1. prognozy [med/max] / ekran 6 h po resecie [cm raw] | info | 0 / 0 / 0/0 h / 163 |
| G3 | NOWY, Twoj workflow: zadnych starych danych w prognozie po resecie TX | PASS | 0 probek |
| G3 | NOWY, Twoj workflow: RX pokazuje pusty zbiornik (raw >= 140) po resecie TX | PASS | 162.73561869142404 |
| G3 | NOWY, Twoj workflow: pierwsza prognoza w < 3 h od resetu TX | PASS | max 0.16666666666666666 |
| G3 | NOWY, odwrotna kolejnosc resetow: brak starych danych | PASS | 0 probek |
| G3 | NOWY, bez RESET RX (zapomniany): TX czyszczacy historie wystarcza - brak starych danych | PASS | 0 probek |
| G3b | czujnik poza zbiornikiem (odczyty < 25 cm), prawdziwy poziom ~35 cm: w ilu z 12 przebiegow TX wyslal sztuczne 25.0 (=100%) | info | 30 h: 0/12 ; 36 h: 7/12 ; 42 h: 10/12 |
| G3b | 30 h poza zbiornikiem: TX NIE wysyla sztucznego 25.0 | PASS | 0/12 |
| G4 | straty radia 30%/kierunek, dni 6-20: dostepnosc / mediana bledu STARY | NOWY | info | STARY 100% / 10% | NOWY 100% / 10% |
| G4 | straty radia 60%/kierunek, dni 6-20: dostepnosc / mediana bledu STARY | NOWY | info | STARY 99% / 8% | NOWY 100% / 11% |
| G4 | NOWY przy 30% strat: dostepnosc >= STARY i blad nie gorszy o > 3 pp | PASS |  |
| G5 | 3 resety zasilania TX w dniach 5-10 (10 przebiegow): dostepnosc / mediana bledu STARY | NOWY | info | STARY 100% / 11% | NOWY 100% / 10% |
| G5 | NOWY: reset TX bez wywozu nie kasuje prognozy (dostepnosc >= 97%, blad <= 15%) | PASS | 100% / 10% |
| G5 | NOWY: wplyw dryfu zegara RTC TX (czas liczony z zadanych snow) na blad prognozy [mediana | p90] | info | -5%: 9% | 22% ; +0%: 9% | 18% ; +5%: 9% | 16% |
| G5 | NOWY: dryf RTC +-5% nie psuje prognozy (mediana <= 15%) | PASS | {-0.05: '9%', 0.0: '9%', 0.05: '9%'} |
| G7 | usterki jak E1 (16 przebiegow x 45 dni): widok DOBRY / BLEDNY / falszywe 'pelny' h  STARY | NOWY | info | STARY 94.0% / 0.9% / 1.9 h | NOWY 94.0% / 0.9% / 1.9 h |
| G7 | NOWY: widok pomiaru nie gorszy od STAREGO (DOBRY >= STARY - 1 pp) | PASS | 94.0 vs 94.0 |
| G7 | NOWY: falszywe 'pelny' nie wiecej niz STARY + 1 h/przebieg | PASS | 1.9 vs 1.9 |
