# Urban Neighbourhoods and Zones Analysis Report

This report presents a spatial and quantitative analysis of **Bangalore's 8 Disjoint Micro-Markets**. The objective is to identify natural **Neighbourhoods** (clusters of three micro-markets that are geographically close), evaluate **pairs of neighbourhoods** for overall city coverage, and rank **Geographic Zones** to assess where high-wealth expansion is best.

---

## 1. Input Micro-Markets & Zone Classification

Micro-markets are assigned to a zone based on their distance and bearing relative to the **data-driven center of the micro-markets** (Latitude: `12.98121`, Longitude: `77.64847`).

| ID | Core Market Name | Zone | Total Units | Avg Affluence Score | Total TAM Families | Combined Score |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| MM1 | **Hagaduru** | South-East | 72,068 | 75.10 | 61,300 | 99.30 |
| MM2 | **Kempapura-Byatarayanapura** | North | 29,100 | 75.40 | 24,752 | 69.72 |
| MM3 | **Belathur-S.M Krishna Ward** | East | 33,657 | 63.88 | 28,625 | 64.07 |
| MM4 | **Ejipura-Sri Lakshmi Devi Ward** | South | 23,959 | 66.62 | 20,384 | 59.44 |
| MM5 | **Yelenahalli-Doddakammanahalli** | South-West | 22,114 | 64.51 | 18,809 | 56.55 |
| MM6 | **Nalwadi Krishnaraja Wadiyar Ward-Malleshwaram** | West | 19,756 | 65.10 | 16,809 | 55.36 |
| MM7 | **Hennur-Lingarajpura** | North | 15,914 | 58.71 | 13,539 | 47.81 |
| MM8 | **Agaram** | Central | 9,721 | 58.79 | 8,269 | 43.57 |

---

## 2. Best Neighbourhoods (Triplets of Micro-Markets)

We evaluated all 56 possible triplets of micro-markets. The tightest neighbourhoods are ranked by their **Average Pairwise Centroid Distance (km)**:

| Rank | Neighbourhood Constituents | Avg Distance (km) | Centroid Zone | Combined TAM Families | Avg Affluence Score | Combined Score |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| #1 | Hagaduru, Ejipura-Sri Lakshmi Devi Ward, Agaram | 7.28 km | South-East | 89,953 | 66.84 | 67.44 |
| #2 | Hagaduru, Belathur-S.M Krishna Ward, Agaram | 7.76 km | East | 98,194 | 65.92 | 68.98 |
| #3 | Nalwadi Krishnaraja Wadiyar Ward-Malleshwaram, Hennur-Lingarajpura, Agaram | 8.11 km | Central | 38,617 | 60.87 | 48.91 |
| #4 | Kempapura-Byatarayanapura, Hennur-Lingarajpura, Agaram | 8.18 km | North | 46,560 | 64.30 | 53.70 |
| #5 | Ejipura-Sri Lakshmi Devi Ward, Nalwadi Krishnaraja Wadiyar Ward-Malleshwaram, Agaram | 8.23 km | Central | 45,462 | 63.50 | 52.79 |
| #6 | Ejipura-Sri Lakshmi Devi Ward, Yelenahalli-Doddakammanahalli, Agaram | 8.29 km | South | 47,462 | 63.31 | 53.19 |
| #7 | Belathur-S.M Krishna Ward, Hennur-Lingarajpura, Agaram | 8.52 km | North-East | 50,433 | 60.46 | 51.82 |
| #8 | Kempapura-Byatarayanapura, Nalwadi Krishnaraja Wadiyar Ward-Malleshwaram, Hennur-Lingarajpura | 8.67 km | North-West | 55,100 | 66.41 | 57.63 |
| #9 | Ejipura-Sri Lakshmi Devi Ward, Yelenahalli-Doddakammanahalli, Nalwadi Krishnaraja Wadiyar Ward-Malleshwaram | 8.67 km | South-West | 56,002 | 65.41 | 57.12 |
| #10 | Ejipura-Sri Lakshmi Devi Ward, Hennur-Lingarajpura, Agaram | 8.73 km | Central | 42,192 | 61.37 | 50.27 |

### Key Finding (Best Neighbourhood):
The geographically tightest neighborhood is **Hagaduru, Ejipura-Sri Lakshmi Devi Ward, Agaram** (comprising MM2, MM6, MM8), situated in the **South-East** sector of the city. It has a tiny average spacing of **7.28 km** and represents an aggregate of **89,953 TAM families** and **66.84 average affluence**.

---

## 3. Top Pairs of Neighbourhoods (6 Micro-Markets Combined)

Pairs of disjoint neighbourhoods are evaluated to identify broad city partitions with maximum aggregate wealth (TAM potential). 

| Rank | Neighbourhood A | Neighbourhood B | Zones Covered | Combined TAM Families | Combined Score |
| :--- | :--- | :--- | :--- | :--- | :--- |
| #1 | Ejipura-Sri Lakshmi Devi Ward, Yelenahalli-Doddakammanahalli, Nalwadi Krishnaraja Wadiyar Ward-Malleshwaram | Hagaduru, Kempapura-Byatarayanapura, Belathur-S.M Krishna Ward | North-East & South-West | 170,679 | 67.41 |
| #2 | Hagaduru, Ejipura-Sri Lakshmi Devi Ward, Yelenahalli-Doddakammanahalli | Kempapura-Byatarayanapura, Belathur-S.M Krishna Ward, Nalwadi Krishnaraja Wadiyar Ward-Malleshwaram | North & South | 170,679 | 67.41 |
| #3 | Hagaduru, Belathur-S.M Krishna Ward, Ejipura-Sri Lakshmi Devi Ward | Kempapura-Byatarayanapura, Yelenahalli-Doddakammanahalli, Nalwadi Krishnaraja Wadiyar Ward-Malleshwaram | South-East & West | 170,679 | 67.41 |
| #4 | Hagaduru, Ejipura-Sri Lakshmi Devi Ward, Nalwadi Krishnaraja Wadiyar Ward-Malleshwaram | Kempapura-Byatarayanapura, Belathur-S.M Krishna Ward, Yelenahalli-Doddakammanahalli | Central | 170,679 | 67.41 |
| #5 | Kempapura-Byatarayanapura, Ejipura-Sri Lakshmi Devi Ward, Nalwadi Krishnaraja Wadiyar Ward-Malleshwaram | Hagaduru, Belathur-S.M Krishna Ward, Yelenahalli-Doddakammanahalli | North-West & South-East | 170,679 | 67.41 |

---

## 4. Geographic Zones Assessment (All 9 Zones)

We grouped the 8 micro-markets into their respective geographic zones to identify which sector of Bangalore is best, representing all 9 sectors:

| Rank | Geographic Zone | Markets Count | Total Units | Total TAM Families | Avg Affluence Score | Avg Combined Score | Included Markets |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| #1 | **South-East** | 1 | 72,068 | 61,300 | 75.10 | 99.30 | Hagaduru |
| #2 | **North** | 2 | 45,014 | 38,291 | 67.06 | 58.77 | Kempapura-Byatarayanapura, Hennur-Lingarajpura |
| #3 | **East** | 1 | 33,657 | 28,625 | 63.88 | 64.07 | Belathur-S.M Krishna Ward |
| #4 | **South** | 1 | 23,959 | 20,384 | 66.62 | 59.44 | Ejipura-Sri Lakshmi Devi Ward |
| #5 | **South-West** | 1 | 22,114 | 18,809 | 64.51 | 56.55 | Yelenahalli-Doddakammanahalli |
| #6 | **West** | 1 | 19,756 | 16,809 | 65.10 | 55.36 | Nalwadi Krishnaraja Wadiyar Ward-Malleshwaram |
| #7 | **Central** | 1 | 9,721 | 8,269 | 58.79 | 43.57 | Agaram |
| #8 | **North-East** | 0 | 0 | 0 | 0.00 | 0.00 | None |
| #9 | **North-West** | 0 | 0 | 0 | 0.00 | 0.00 | None |

## Summary & Recommendation

1. **Top Active Zone**: The **South-East** zone leads in total volume, anchoring **61,300 TAM families** across **1** active micro-market(s) with a solid average affluence score of **75.10**.
2. **Top Individual Value**: The market **Hagaduru** (located in the **South-East** zone) is the single highest-value micro-market with **61,300 TAM families** and a premier affluence score of **75.10**.
3. **Inactive Zones**: Zones such as **North-East**, **North-West** do not contain any of the top 8 recommended micro-markets due to lower relative affluence or residential unit counts in these specific H3 clusters.
