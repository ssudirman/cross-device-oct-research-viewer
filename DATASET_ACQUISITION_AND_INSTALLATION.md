# Obtaining and installing the OCT datasets

Last source-link check: **9 November 2026**.

The viewer does not distribute the public datasets. Each user must obtain the
files from the provider, accept the provider's terms and retain the required
citations. In particular, Duke and AROI prohibit redistribution. Do not include
the downloaded archives or extracted datasets in a public release of the
viewer.

## 1. Obtain the datasets

### Duke AMD/control

Use the [official Duke/Farsiu AMD dataset page](https://people.duke.edu/~sf59/RPEDC_Ophth_2013_dataset.htm).
Download the separate files for the 269 AMD subjects and 115 control subjects.
The archive names used by this installer are `AMD.zip` and `Control.zip`.
The Duke page limits use to research/education, requires citation of Farsiu
et al. (2014), and prohibits commercialisation and redistribution.

### Duke DME 2015

Use the [official Duke/Farsiu DME dataset page](https://people.duke.edu/~sf59/Chiu_BOE_2014_dataset.htm)
and download the full dataset ZIP. The expected filename is
`2015_BOE_Chiu2.zip`; it contains `Subject_01.mat` through `Subject_10.mat`.
The same Duke research/education, citation and non-redistribution conditions
apply.

### JHU healthy-control/multiple-sclerosis dataset

Use the [official Johns Hopkins IACL OCT Data page](https://iacl.ece.jhu.edu/index.php/OCT_Data).
Download `OCT_Manual_Delineations-2018_June_29_b.zip` (approximately 1.8 GB).
It contains 35 Spectralis `.vol` files, 35 corresponding delineation MAT files,
the demographics CSV and README. Cite He et al. (2019), as requested on the
provider page.

### AROI

Use the [official AROI database page](https://ipg.fer.hr/ipg/resources/oct_image_database).
The provider asks users to email Martina Melinščak for access. The project copy
is `AROI.rar`, containing the published 24-patient/3,072-B-scan release. AROI
permits research and educational use but prohibits copying, redistribution and
unauthorised commercial use. Cite Melinščak et al. (2021).

### OCT5K annotations and underlying Rasti images

1. Download the annotation package from the
   [UCL Research Data Repository](https://rdr.ucl.ac.uk/articles/dataset/OCT5k_A_dataset_of_multi-disease_and_multi-graded_annotations_for_retinal_layers/22128671/4)
   (DOI [`10.5522/04/22128671`](https://doi.org/10.5522/04/22128671)). The
   expected archive is `OCT5k.zip`.
2. The OCT5K annotation package does **not** contain the original OCT images.
   Follow its supplied `Scripts/Prepare_Images_Download.ipynb` to obtain the
   underlying Rasti archive, `Macular-Dataset-R.Rasti_old.rar`, from the source
   identified by the OCT5K authors.
3. Obtain the password for the four nested Rasti ZIPs from the Rasti provider's
   [dataset page for the 50-normal/48-AMD/50-DME OCT collection](https://hrabbani.site123.me/available-datasets/dataset-for-oct-classification-50-normal-48-amd-50-dme).
   The password is deliberately not reproduced by this project or stored by the
   installer.

`Macular Dataset-Heidelberg.rar` contains a separate `Dataset_3x50_Final`
tree. It was downloaded during data preparation but was **not used by the
experiments or the viewer registry**, so the installer ignores it.

## 2. Arrange the downloaded archives

Put the provider archives in this layout. The names are checked literally:

```text
Cross-Device OCT/
├── AROI/
│   └── AROI.rar
├── Duke/
│   ├── AMD.zip
│   └── Control.zip
├── Duke DME/
│   └── 2015_BOE_Chiu2.zip
├── JHU/
│   └── OCT_Manual_Delineations-2018_June_29_b.zip
└── OCT5K/
    ├── OCT5k.zip
    ├── Macular-Dataset-R.Rasti_old.rar
    └── Macular Dataset-Heidelberg.rar       # retained but not used
```

## 3. Prerequisites

- Python 3.10 or later;
- Pillow (included in `oct_viewer/requirements.txt`);
- a RAR-capable extractor available as `7z`, `tar`, or `unrar`.

Windows 10/11 normally supplies a compatible `tar.exe`. If it does not, install
[7-Zip](https://www.7-zip.org/) and ensure `7z.exe` is available on `PATH`.

Allow approximately 26 GB of free space under the target location. The staging
directory is created inside `oct_viewer/datasets` and renamed into place, so it
does not require a second full-sized copy.

## 4. Run the installer

From the extracted `oct_viewer` directory, using the Python environment in
which `requirements.txt` was installed:

```powershell
python scripts\install_datasets.py `
  --archive-root 'C:\path\to\Cross-Device OCT'
```

The installer will prompt for the Rasti password without echoing it. It does
not download anything and it never saves or prints the password.

For safety, the installer refuses to overwrite any non-empty built-in dataset
directory. To check an existing installation without extracting anything:

```powershell
python scripts\install_datasets.py --verify-only
```

## 5. What the installer produces

The output matches the viewer's portable relative-path configuration:

```text
oct_viewer/datasets/
├── oct5k_annotations/
├── oct5k_raw/
├── aroi/
├── duke_amd/
├── jhu/
├── duke_dme/
└── custom_dataset/
    └── scans/
```

OCT5K requires an additional deterministic step. The installer reads the
downloaded `manual_paths.csv` and `automatic_paths.csv`, finds the locally
available Rasti images, and produces the 512 × 512 PNGs used by the viewer:

- 1,672 manually annotated images in `Images/Images_Manual`;
- 2,562 locally resolvable automatically annotated images in
  `Images/Images_Automatic`.

Rows referring to `Dataset_3x50_Final` or Kermany `CellData` are not part of
the experimental image set and are skipped. The installer validates all final
counts before committing the staged directories.

## 6. Expected validation counts

| Check | Expected |
|---|---:|
| Duke AMD MAT files | 269 |
| Duke control MAT files | 115 |
| Duke DME MAT files | 10 |
| JHU `.vol` files | 35 |
| JHU delineation MAT files | 35 |
| AROI PNG files, including raw images and masks | 6,780 |
| OCT5K/Rasti raw TIFF or PNG files | 4,388 |
| OCT5K manually staged PNGs | 1,672 |
| OCT5K automatically staged PNGs | 2,562 |

These counts describe the exact copies used to build the viewer's released
scan indexes. A provider may publish a later version with different contents;
such a version should be reviewed before rebuilding the registry rather than
silently accepted as equivalent.
