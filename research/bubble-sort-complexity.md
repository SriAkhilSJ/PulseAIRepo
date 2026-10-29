# Research: Time and Space Complexity of Bubble Sort

## Summary

Bubble sort repeatedly steps through the list, compares adjacent elements, and swaps them
if they are out of order. Each pass "bubbles" the largest remaining unsorted element to its
final position at the end of the array. It performs `n-1` passes over a shrinking window,
giving ~`n(n-1)/2` comparisons in the general case — hence **O(n²)** for average and worst
case.

- **Worst case (reversed input):** every pair is out of order, so every comparison produces
  a swap. Total comparisons = `n(n-1)/2` → **O(n²)** (GeeksforGeeks derivation: sum over
  passes).
- **Average case:** on random input, roughly half the pairs are inverted; GeeksforGeeks
  derives comparisons ≈ `N² - N²/2 = N²/2` → still **O(n²)** (quadratic growth dominates).
- **Best case (already sorted) with the "swapped flag" optimization:** the first full pass
  makes zero swaps, the flag stays unset, and the algorithm exits after a single pass of
  `n-1` comparisons → **O(n)**.
- **Space complexity:** **O(1)** — only a constant number of temporaries (loop indices,
  swap variable, flag); sorting is done in place.

### Why the optimized variant gets O(n) best case

The optimization records whether any swap happened during a pass. If a full pass completes
with no swaps, the array must already be sorted (bubble sort's swaps are the only thing
changing the array), so further passes cannot accomplish anything and the algorithm
terminates early. On already-sorted input this triggers after exactly one pass: `n-1`
comparisons, `0` swaps → Θ(n). Without the flag, the naive version still runs all
`n-1` passes even on sorted input and remains O(n²) in every case.

## Complexity Table

| Case            | Time    | Reason                                                        |
|-----------------|---------|---------------------------------------------------------------|
| Best (sorted)   | O(n)    | Optimized variant: 1 pass, 0 swaps, early exit.               |
| Average         | O(n²)   | ~N²/2 comparisons on random input (GfG derivation).           |
| Worst (reverse) | O(n²)   | All n(n-1)/2 pairs compared and swapped.                      |
| Space           | O(1)    | In-place; constant extra temporaries.                         |

Other properties (per Wikipedia): stable sort; historically significant (Friend 1956,
Iverson naming) but primarily educational now — outperformed by quicksort/merge sort in
practice.

## Sources

1. GeeksforGeeks — *Time and Space Complexity Analysis of Bubble Sort*
   https://www.geeksforgeeks.org/dsa/time-and-space-complexity-analysis-of-bubble-sort/
   (worst-case N(N-1)/2 derivation, average-case N²/2 derivation, O(1) space)
2. Wikipedia — *Bubble sort*
   https://en.wikipedia.org/wiki/Bubble_sort/
   (best case O(n) with early-exit optimization, stability, history)
3. GeeksforGeeks — *Bubble Sort Algorithm*
   https://www.geeksforgeeks.org/dsa/bubble-sort-algorithm/
   (in-place, no additional memory, stability)
4. Reference note: the algorithm's full formal treatment appears in
   Knuth, *The Art of Computer Programming* Vol. 3 (Sorting and Searching), §5.2.2;
   CLRS covers exchange sorts in its sorting chapter but does not feature bubble sort
   prominently — it treats it as a pedagogical baseline.
