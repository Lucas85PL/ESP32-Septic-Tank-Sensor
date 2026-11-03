# Symulacja 2 - iteracje logiki (50 dni, 300 przebiegow na wariant)

Punkt startowy iteracji: TX 1.4.7 (V0). V1: klastry probek zamiast konsensusu serii; V2: + wybor klastra zgodnego z oczekiwanym zakresem (prior) + odniesienie w flash po resecie TX; V3: + rozszerzone ponawianie wysylki z ponownym pomiarem.

| Metryka | SUFIT (idealny czujnik) | 1.4.5 (v1.5.0) | V0 (TX 1.4.7) | V1 klastry probek | V2 klastry+prior+persist | V3 (rekomendowana) |
|---|---|---|---|---|---|---|
| Widok odbiornika DOBRY (blad <= 10 cm) [% czasu] | 98.8 | 83.2 | 93.5 | 96.3 | 96.3 | 96.4 |
| Widok NIEAKTUALNY (brak swiezych danych > 26 h) [%] | 0.2 | 4.4 | 4.2 | 1.5 | 1.4 | 1.4 |
| Widok BLEDNY (swieze, ale zle dane) [%] | 1.1 | 12.4 | 1.9 | 2.2 | 2.2 | 2.2 |
| Sredni blad widoku [cm] | 2.9 | 12.1 | 6.9 | 5.3 | 5.2 | 5.2 |
| Dostarczone bledne wartosci (> 8 cm) [szt./50 dni] | 0.00 | 8.50 | 0.21 | 0.20 | 0.18 | 0.17 |
| w tym grube bledy (> 20 cm) [szt./50 dni] | 0.00 | 6.73 | 0.16 | 0.15 | 0.12 | 0.13 |
| Dostarczone wartosci ogolem [szt./50 dni] | 97.0 | 88.2 | 72.9 | 93.7 | 94.5 | 95.5 |
| Wykrycie wywozu: mediana / p95 [h] (nie wykryto %) | 5.7 / 11.7 (0%) | 21.3 / 31.2 (0%) | 24.2 / 48.8 (0%) | 21.1 / 31.5 (0%) | 20.9 / 31.2 (0%) | 20.8 / 30.8 (0%) |
| Powrot po resecie TX: mediana / p95 [h] (nie wrocil %) | 5.9 / 11.8 (0%) | 0.2 / 181.2 (1%) | 0.1 / 24.1 (0%) | 0.1 / 12.1 (0%) | 0.1 / 12.1 (0%) | 0.1 / 12.1 (0%) |
| Powrot po awarii odbiornika: mediana / p95 [h] (nie wrocil %) | 6.3 / 11.4 (0%) | 7.5 / 151.3 (0%) | 8.5 / 32.7 (0%) | 6.2 / 12.8 (0%) | 6.2 / 11.8 (0%) | 1.0 / 8.5 (0%) |
| Cykle: OK / NO_VALID / JUMP_REJ / DEADZONE | 100 / 0 / 0 / 0 | 91 / 9 / 0 / 0 | 75 / 26 / 1 / 0 | 96 / 4 / 1 / 0 | 97 / 3 / 1 / 0 | 97 / 3 / 1 / 0 |
| Czas aktywnosci [min/dobe] | 5.3 | 16.4 | 5.4 | 5.5 | 5.5 | 5.6 |

## Test odporności (trudniejsze błędy niż w założeniach, 300 przebiegów)

| Warunki | Wariant | Widok dobry [%] | Nieaktualny [%] | Bledne dostawy [szt./50 dni] | Cykle NO_VALID | min/dobe |
|---|---|---|---|---|---|---|
| Trudniej: błędy próbek 30-85%, zepsute serie 20-70% | 1.4.5 | 70.2 | 4.0 | 21.18 | 10.1 | 14.2 |
| | V0 (TX 1.4.7) | 49.4 | 45.4 | 0.30 | 77.6 | 5.3 |
| | V3 | 91.5 | 5.7 | 0.58 | 29.3 | 5.5 |
| | V3 + 8 serii | 92.6 | 4.9 | 0.32 | 28.4 | 7.5 |
| Bardzo trudno: błędy 50-90%, zepsute serie 30-80% | 1.4.5 | 60.2 | 3.9 | 31.81 | 9.8 | 13.2 |
| | V0 (TX 1.4.7) | 17.8 | 63.6 | 0.53 | 94.0 | 5.3 |
| | V3 | 59.4 | 34.6 | 1.77 | 65.1 | 5.4 |
| | V3 + 8 serii | 55.3 | 39.3 | 1.44 | 69.6 | 7.4 |

## Sweepy parametrów (baza V1/V3, warunki z założeń)

- Liczba serii: 3 serie = 2,5 min/dobę, ale 0,52 błędnej dostawy; 4 serie = 0,44; **6 serii = 0,17**; 8 serii = 0,16 przy 7,4 min/dobę.
- Czas snu: 6 h zamiast 12 h daje 1,59 błędnej dostawy na przebieg (2× więcej cykli w oknach wyjęcia czujnika) i 2× więcej energii.
- Okno napełniania (8-15 cm/dobę + 3-5 cm): bez wpływu na wyniki. Zostaje 15 cm/dobę + 5 cm.
- max_rej: 1 → 0,37 błędnej dostawy (gorzej), 2 → 0,17, 3 → 0,17. Zostaje 2.
- pool_min (12 z 60 próbek): niższe progi (8, 10) dają więcej błędów, wyższe (20) więcej ciszy.
