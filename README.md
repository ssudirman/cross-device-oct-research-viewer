# Cross-Device OCT Research

Local, single-user browser application for browsing the five project datasets,
displaying the 365 released prediction files from the 55 paper-relevant model
instances, registering Custom B-scans, and running those models on Custom data.
The separate **Study results** view presents the packaged exploratory,
selection, factorial and untouched-cohort analyses without recomputing them.

The application never writes to a built-in dataset or to the supplied result
folders. It binds to `127.0.0.1` by default and is for research use only.

Released prediction arrays and inference checkpoints are stored under the
application root rather than the surrounding research workspace:

```text
results/
  exploratory/predictions/
  exploratory/analysis/
  matched-baseline/predictions/
  confirmatory/predictions/
  confirmatory/analysis/
  selection/
  source-validation/
  provenance/
  study_results.json
models/
  factorial/
  matched-baseline/
```

## Local dataset layout

The bundled working layout keeps datasets under `oct_viewer/datasets/`:

```text
datasets/
  oct5k_annotations/
  oct5k_raw/
  aroi/
  duke_amd/
  jhu/
  duke_dme/
  custom_dataset/
```

Built-in dataset roots are stored as portable paths relative to the
`oct_viewer` directory (for example, `datasets/duke_amd`). The Custom dataset
root is likewise stored as `datasets/custom_dataset`. See `DATASET_SETUP.md`
for the source dataset mapping.

## Install the application dependencies

The supplied `requirements.txt` contains everything needed to use the complete
application, including the pinned PyTorch build required to run the 55 trained
models. Open a terminal in the `oct_viewer` folder and run:

```powershell
python -m pip install -r requirements.txt
```

## Install the released models and predictions

The GitHub repository intentionally excludes approximately 5.8 GiB of trained
model checkpoints and stored prediction arrays. They are archived under the
versioned Zenodo record `10.5281/zenodo.24109134`.

After installing the Python dependencies, download, verify and install every
binary-asset package with:

```powershell
python scripts/install_release_assets.py
```

The installer checks the expected byte size and SHA-256 hash of each archive,
extracts only allow-listed relative paths and verifies every installed file.
Interrupted downloads are resumed when the server supports byte ranges. To
check an existing installation without downloading anything, run:

```powershell
python scripts/install_release_assets.py --verify-only
```

The application can open without these packages, but stored prediction
overlays and new model inference are available only for assets that have been
installed successfully.

As a manual alternative, download the five binary ZIP archives from Zenodo and
extract each one **into this `oct_viewer/` directory** (the directory containing
`run_viewer.py`). These archives begin with `models/` or `results/` and do not
contain another outer `oct_viewer/` folder. The Zenodo-level `README.md`,
`asset_manifest.json` and `SHA256SUMS.txt` are documentation/provenance files;
they do not belong inside the installed application.

## Run

From the `oct_viewer` folder:

```powershell
python run_viewer.py
```

Then open <http://127.0.0.1:8765>.

For provider links and a reproducible archive-to-dataset installation process,
see `DATASET_ACQUISITION_AND_INSTALLATION.md` and
`scripts/install_datasets.py`.

For an end-user explanation of dataset coverage and why some B-scans do not
have ready-made overlays, see `PREDICTION_RESULT_AVAILABILITY.md`.

