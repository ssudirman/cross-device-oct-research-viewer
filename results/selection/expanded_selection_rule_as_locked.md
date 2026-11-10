# Expanded comparator reanalysis rule

Status: **frozen retrospective reanalysis specification**  
Date: 2026-11-03  

This specification leaves the original documents 20--23, their locks, and all
original results unchanged. It reprocesses copied exploratory and confirmatory
result tables without retraining a model or rerunning inference.

## Recipe selection

The recipe candidates and score are unchanged from document 20:

- candidates: `V100`, `V010`, `V001`, `V110`, `V101`, `V011`, `V111`;
- reference: `V000`;
- score: the mean, over the three exploratory datasets and five seeds, of the
  candidate's unit-macro error divided by the seed-matched `V000` error;
- tie margin: 0.02, resolved in favour of fewer active components and then the
  lower score.

## Expanded comparator selection

The comparator candidates are expanded to:

- `B1_HM` (training-time histogram matching);
- `B2_GINIPA`;
- `B3_MT` (mean teacher);
- `V001` (FDA only);
- `V100` (lateral-scale augmentation only);
- `V010` (rectangle occlusion only).

The same score and tie rule are used. A candidate equal to the selected recipe
would be removed, as in document 20.

## Re-evaluation

The copied per-seed, per-unit confirmatory table is analysed with the original
document 20/document 23 estimand and hierarchical seed-by-unit paired
bootstrap: 10,000 draws using NumPy `default_rng(20261014)`. The non-inferiority
margin remains 1.62 micrometres.

The reanalysis reports:

1. `H1`: selected recipe minus `V000`;
2. amended `H2`: selected recipe minus the expanded selected comparator;
3. the existing `V100 - V000`, `V010 - V000`, and `V001 - V000` contrasts.

No original protocol, prediction, condition record, analysis output, or data
file is overwritten.
