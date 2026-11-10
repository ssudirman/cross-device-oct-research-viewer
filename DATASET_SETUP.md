# Dataset setup guide

The viewer does not distribute OCT images or annotations. Obtain each dataset
from its provider and configure its root under **Dataset roots** in the browser.
The viewer checks canonical decoded pixels scan by scan. A matching scan receives
its supplied overlays; a mismatch remains viewable but receives no overlay.

Do not rename individual provider files after building the local indexes. Outer
archive directory names may differ: select the root described below.

## OCT5K

1. Obtain the annotation package from the UCL Research Data Repository.
2. Obtain the Rasti raw macular images from their
   [dataset page for the 50-normal/48-AMD/50-DME OCT collection](https://hrabbani.site123.me/available-datasets/dataset-for-oct-classification-50-normal-48-amd-50-dme).
   Obtain any archive password directly from that page; this project does not
   reproduce it.
3. Keep separate raw and annotation roots.
4. Run `scripts/stage_oct5k_images.py` with the raw root, annotation root, and
   the appropriate `manual_paths.csv` or `automatic_paths.csv`.
5. Configure:
   - **OCT5K annotations:** the directory containing `Images/Images_Manual`,
     `Images/Images_Automatic`, and the annotation folders;
   - **OCT5K raw images:** the extracted Rasti root.

The viewer displays the staged 512 × 512 PNG, not the raw 512 × 496 TIFF.
OCT5K is pixels-only because its physical spacing is not verified. Rows in the
automatic path list that refer to unavailable `Dataset_3x50_Final` or `CellData`
sources are expected to be skipped.

The Pillow staging route reproduces every stored project PNG at the decoded-pixel
level. Equivalence to the provider notebook's OpenCV route has not been tested.

## Duke AMD/control

1. Obtain the dataset from the Duke dataset page under its research-use terms.
2. Select the directory containing:

```text
AMD/       269 MAT files in the project copy
Control/   115 MAT files in the project copy
```

The adapter reads the `images` array and discovers each volume's real third
dimension; it does not assume 100 scans. The current provider archive's outer
unpack layout has not been retested, so select the directory that directly
contains `AMD` and `Control`.

## Duke DME 2015

1. Obtain the public dataset from the Duke dataset page.
2. Select the directory containing `Subject_01.mat` through `Subject_10.mat`.

The adapter browses all 610 B-scans and uses the released portable index for the
110 scans with stored predictions. Labelled B-scan numbers differ by subject.
The archive's outer unpack layout has not been retested.

## JHU HC/MS

1. Obtain `OCT_Manual_Delineations-2018_June_29_b.zip` from the IACL resource
   page. The project record describes it as approximately 1.8 GB.
2. Select the root that directly contains `vol/` and `delineation/`, each with
   35 eye files in the project copy.

The demographics CSV is not needed. The viewer reads only non-identity `.vol`
header fields required for image dimensions, offsets, and spacing. It applies
the same invalid-to-zero, clipping, fourth-root display transform used by the
experiment. The fresh provider archive's outer unpack layout has not been tested.

## AROI

1. Request AROI from its provider under the provider's terms.
2. Select the directory containing the patient collection, for example:

```text
24 patient/
  patient1/
    raw/ALL/
    raw/labeled/
    mask/
```

The project copy has 24 patients and 3,072 scans, while the provider page
describes 25 patients and 3,200 scans. The viewer therefore validates scan by
scan and does not require one fixed total. Extra scans are browsable without
supplied overlays.

## Custom

Custom is local application data, not a released dataset. Version 1 accepts:

- one-frame greyscale PNG or TIFF;
- JPEG with a lossy-compression warning;
- 16-bit display-scaled images only after explicit confirmation.

Non-grey RGB, multi-page TIFF, floating-point, incorrectly oriented, and
oversized images are rejected. Custom images and results are stored under the
application and are excluded from release packaging.

## Research-use warning

The viewer and its predictions are for research use only. They are not for
clinical diagnosis, treatment, or patient management. Users are responsible
for complying with every source dataset's terms when displaying or exporting
locally installed images.

# Dataset locations

The viewer's default portable layout is relative to the `oct_viewer` root:

| Viewer dataset | Relative location | Original project source |
|---|---|---|
| OCT5K annotations/staged images | `datasets/oct5k_annotations` | `data/oct5k_annotations` |
| OCT5K raw images | `datasets/oct5k_raw` | `data/oct5k` |
| AROI | `datasets/aroi` | `data/AROI` |
| Duke AMD/control | `datasets/duke_amd` | `data/duke` |
| JHU HC/MS | `datasets/jhu` | `data/jhu_hcms` |
| Duke DME 2015 | `datasets/duke_dme` | `data/duke_dme_chiu2015` |
| Custom | `datasets/custom_dataset` | Managed by the viewer |

The application resolves these relative paths against `oct_viewer/`, not the
current shell directory. Dataset-root settings may still point outside the app;
external selections are necessarily stored as absolute paths.

