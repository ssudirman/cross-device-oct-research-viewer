# Dataset and prediction-result availability

## Why some images show “no supplied result”

The application lets you browse all B-scans that it can identify in an
installed dataset. However, the supplied prediction files cover only the
B-scans that were processed in the research experiments. Consequently, some
images can be opened even though no ready-made prediction overlay is available
for them.

In the scan browser, **“no supplied result” means that the application package
does not contain a stored model prediction for that B-scan**. It does not mean
that:

- the image is damaged;
- the dataset was installed incorrectly; or
- the trained models are unable to process the image.

A volume is a three-dimensional OCT acquisition made up of multiple B-scans.
Prediction availability is recorded at the B-scan level. Therefore, a volume
can contain some B-scans with supplied results and other B-scans without them.

## Coverage of the installed datasets

| Dataset | B-scans that can be browsed | B-scans with supplied results | B-scans without supplied results | Why some results are unavailable |
|---|---:|---:|---:|---|
| **OCT5K** | 4,234 | 1,668 | 2,566 | Supplied results cover 1,265 quality-controlled, manually annotated AMD/healthy B-scans and 403 manually annotated DME B-scans. The remaining images are primarily from the automatically annotated subset, which was used only as an unlabelled source of OCT5K appearance information in this study. Four manually annotated AMD/healthy scans were also excluded by a predefined annotation-geometry quality check. |
| **AROI** | 3,072 | 1,136 | 1,936 | The experiments produced stored predictions for the 1,136 labelled B-scans used in the evaluation. The remaining 1,936 B-scans did not have the reference labels required for that evaluation. |
| **Duke AMD/control** | 38,382 | 0 | 38,382 | This was the source dataset used to train the models. The released project contains aggregate source-validation measurements but not stored per-scan predictions for all 38,382 source images. |
| **JHU healthy/multiple-sclerosis** | 1,715 | 1,715 | 0 | Every indexed JHU B-scan has supplied confirmatory-evaluation predictions. |
| **Duke DME 2015** | 610 | 110 | 500 | The confirmatory evaluation used 110 annotated B-scans. The other 500 scans were not part of the labelled evaluation subset, so ready-made predictions were not packaged for them. |
| **Custom** | Depends on the user | None initially | Depends on the user | A newly registered Custom image has no result until the user runs one or more installed models on it. |

These figures describe the supplied application package, not the total number
of images that the models are technically capable of processing.

## Why the number of available models also varies

Having a supplied result does not necessarily mean that all 55 models were
run on that scan. The available models depend on the role of the dataset in the
research:

- **OCT5K manual AMD/healthy, OCT5K manual DME and AROI AX1:** predictions from
  all 55 paper-relevant models are supplied for each covered B-scan.
- **AROI AX2, AX3 and AX4:** 40 factorial-model predictions are supplied for
  each of the 1,136 covered B-scans. These are preprocessing-control views; the
  15 matched-baseline models were not evaluated using these views.
- **JHU and Duke DME:** 40 predictions are supplied for each covered B-scan.
  They comprise five experimental recipes (`V000`, `V001`, `V010`, `V100` and
  `V111`) and three matched-baseline methods, with five independently trained
  models (seeds) for each recipe or method. The factorial recipes `V011`,
  `V101` and `V110` were not evaluated on these confirmatory cohorts.

The result filters show only predictions that actually exist for the selected
B-scan and evaluation view.

## Obtaining a prediction for an uncovered B-scan

To process a built-in B-scan that has no supplied result:

1. Select the B-scan in the dataset browser.
2. Choose **Add this scan to Custom**.
3. Open the resulting Custom entry.
4. Run the required installed model or models.

Predictions generated in this way are labelled **user-generated exploratory
results**. They were not part of the original paper's evaluation and do not
have reference-label error measurements merely because an overlay has been
generated. They should not be treated as additional evidence for the study
without an appropriate evaluation protocol and reference annotations.

## Pixel-validation warnings are different

The application also checks whether an installed image with supplied results
matches the exact image used in the research. If its pixel hash differs, the
application disables the stored overlay and displays a pixel-validation
warning. This protects against applying a prediction to a differently resized,
recompressed or otherwise altered image.

Therefore:

- **No supplied result:** no stored prediction was registered for that B-scan.
- **Pixel-validation warning:** a stored prediction exists, but the locally
  installed image does not exactly match the image on which it was produced.

## Research-use notice

All supplied and newly generated predictions are for research use only. They
must not be used for clinical diagnosis, treatment or patient management.
