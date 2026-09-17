# BactoIndex Installation Guide for macOS

## 1. Install Homebrew

Check whether Homebrew is already installed:

```bash
brew --version
```

If not installed:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

## 2. Install Python and Tkinter

```bash
brew install python
brew install python-tk@3.13
```

Verify:

```bash
/opt/homebrew/bin/python3 --version
```

Test Tkinter:

```bash
/opt/homebrew/bin/python3 -c "import tkinter; tkinter.Tk().destroy(); print('Tkinter works')"
```

## 3. Download the Software

Place the following files into a folder:

- BactoIndex_v6_1.py
- requirements.txt

Example:

```bash
mkdir ~/Desktop/BactoIndex
```

## 4. Create a Virtual Environment

```bash
cd ~/Desktop/BactoIndex
/opt/homebrew/bin/python3 -m venv .venv
source .venv/bin/activate
```

## 5. Install Required Packages

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 6. Run the Software

```bash
source .venv/bin/activate
python BactoIndex_v6.0.py
```

## 7. Troubleshooting

### Missing package error

```bash
python -m pip install -r requirements.txt
```

### Tkinter error

```bash
brew install python-tk@3.13
```

Recreate the virtual environment afterwards.

### Excel file cannot be opened

Verify that all dependencies from requirements.txt were installed successfully.
