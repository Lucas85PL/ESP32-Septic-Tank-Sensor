# Symulacja 3 - bledy czujnika z logu pomiary.txt (200 przebiegow, 50 dni)

Nowe epizody: falszywe echo ~25,4 cm (12-36 h x2, 60-84 h x1), czujnik slepy (12-48 h x2), slepy ponizej 25 cm (12-48 h). Opis w sim3.py. V3 = v1.7.0, V4 = v1.7.1.

## Z nowymi bledami (FAULTS=1)
| Metryka | SUFIT (idealny czujnik) | 1.4.5 (v1.5.0) | V3 (rekomendowana) | V4 (v1.7.1 poprawki) |
|---|---|---|---|---|
| Widok odbiornika DOBRY (blad <= 10 cm) [% czasu] | 98.8 | 75.4 | 86.9 | 90.0 |
| Widok NIEAKTUALNY (brak swiezych danych > 26 h) [%] | 0.2 | 11.4 | 4.9 | 7.4 |
| Widok BLEDNY (swieze, ale zle dane) [%] | 1.1 | 13.2 | 8.2 | 2.6 |
| Sredni blad widoku [cm] | 2.9 | 14.6 | 10.4 | 6.5 |
| Dostarczone bledne wartosci (> 8 cm) [szt./50 dni] | 0.00 | 8.81 | 4.60 | 0.48 |
| w tym grube bledy (> 20 cm) [szt./50 dni] | 0.00 | 7.33 | 4.29 | 0.24 |
| Dostarczone wartosci ogolem [szt./50 dni] | 97.0 | 72.9 | 80.3 | 78.9 |
| Wykrycie wywozu: mediana / p95 [h] (nie wykryto %) | 5.5 / 11.7 (0%) | 20.9 / 30.3 (0%) | 20.7 / 30.9 (0%) | 20.7 / 31.3 (0%) |
| Powrot po resecie TX: mediana / p95 [h] (nie wrocil %) | 5.9 / 11.8 (0%) | 0.2 / 253.9 (2%) | 0.1 / 48.2 (0%) | 0.1 / 36.2 (0%) |
| Powrot po awarii odbiornika: mediana / p95 [h] (nie wrocil %) | 5.8 / 11.3 (0%) | 10.4 / 198.9 (1%) | 1.6 / 63.1 (0%) | 1.5 / 40.2 (0%) |
| Cykle: OK / NO_VALID / JUMP_REJ / DEADZONE | 100 / 0 / 0 / 0 | 75 / 25 / 0 / 0 | 82 / 9 / 10 / 0 | 80 / 20 / 1 / 0 |
| Czas aktywnosci [min/dobe] | 5.3 | 14.5 | 5.6 | 5.6 |
| Falszywe "pelny" (<= 30 cm przy poziomie >= 40) [szt./50 dni] | 0.00 | 1.23 | 4.33 | 0.26 |
| Przebiegi z >= 1 falszywym "pelny" [%] | 0 | 33 | 99 | 18 |

## Kontrola regresji, bez nowych bledow (FAULTS=0)
| Metryka | SUFIT (idealny czujnik) | 1.4.5 (v1.5.0) | V3 (rekomendowana) | V4 (v1.7.1 poprawki) |
|---|---|---|---|---|
| Widok odbiornika DOBRY (blad <= 10 cm) [% czasu] | 98.8 | 82.8 | 96.4 | 96.4 |
| Widok NIEAKTUALNY (brak swiezych danych > 26 h) [%] | 0.2 | 4.7 | 1.4 | 1.4 |
| Widok BLEDNY (swieze, ale zle dane) [%] | 1.1 | 12.5 | 2.2 | 2.2 |
| Sredni blad widoku [cm] | 2.9 | 12.3 | 5.2 | 5.2 |
| Dostarczone bledne wartosci (> 8 cm) [szt./50 dni] | 0.00 | 8.59 | 0.13 | 0.13 |
| w tym grube bledy (> 20 cm) [szt./50 dni] | 0.00 | 6.84 | 0.09 | 0.09 |
| Dostarczone wartosci ogolem [szt./50 dni] | 97.0 | 87.9 | 95.4 | 95.4 |
| Wykrycie wywozu: mediana / p95 [h] (nie wykryto %) | 5.5 / 11.7 (0%) | 21.1 / 31.2 (0%) | 20.7 / 30.9 (0%) | 20.7 / 30.9 (0%) |
| Powrot po resecie TX: mediana / p95 [h] (nie wrocil %) | 5.9 / 11.8 (0%) | 0.2 / 193.2 (0%) | 0.1 / 12.1 (0%) | 0.1 / 12.1 (0%) |
| Powrot po awarii odbiornika: mediana / p95 [h] (nie wrocil %) | 5.8 / 11.3 (0%) | 7.8 / 177.8 (0%) | 1.0 / 11.0 (0%) | 1.0 / 11.0 (0%) |
| Cykle: OK / NO_VALID / JUMP_REJ / DEADZONE | 100 / 0 / 0 / 0 | 91 / 10 / 0 / 0 | 97 / 3 / 1 / 0 | 97 / 3 / 1 / 0 |
| Czas aktywnosci [min/dobe] | 5.3 | 16.3 | 5.6 | 5.6 |
| Falszywe "pelny" (<= 30 cm przy poziomie >= 40) [szt./50 dni] | 0.00 | 0.01 | 0.03 | 0.03 |
| Przebiegi z >= 1 falszywym "pelny" [%] | 0 | 0 | 2 | 2 |
