# BactoIndex Installation Guide for Windows

## 1. Install Python and Tkinter

Download the latest Python 3.13 installer from the official website:

https://www.python.org/downloads/windows/

Run the installer and, on the first screen, tick **Add python.exe to PATH** before clicking **Install Now**. Tkinter is included with the standard Windows installer, so no separate package is required.

Verify the installation by opening a new **Command Prompt** (press the Windows key, type `cmd`, and press Enter):

```bat
python --version
```

Test Tkinter:

```bat
python -c "import tkinter; tkinter.Tk().destroy(); print('Tkinter works')"
```

If `python` is not recognised, close and reopen the Command Prompt, or use `py` in place of `python` throughout this guide.

## 2. Download the Software

Place the following files into a folder:

- BactoIndex_v6_1.py
- requirements.txt

Example:

```bat
mkdir %USERPROFILE%\Desktop\BactoIndex
```

## 3. Create a Virtual Environment

```bat
cd %USERPROFILE%\Desktop\BactoIndex
python -m venv .venv
.venv\Scripts\activate
```

After activation, the prompt is prefixed with `(.venv)`.

If you are using **PowerShell** instead of Command Prompt, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

Should PowerShell block the script with an execution-policy error, run the following once, then activate again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

## 4. Install Required Packages

```bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 5. Run the Software

```bat
.venv\Scripts\activate
python BactoIndex_v6.0.py
```

## 6. Troubleshooting

### Missing package error

```bat
python -m pip install -r requirements.txt
```

### Tkinter error

Reinstall Python from https://www.python.org/downloads/windows/ and, in the installer, choose **Modify**, then ensure **tcl/tk and IDLE** is selected. Recreate the virtual environment afterwards.

### "python" is not recognised

Either reopen the Command Prompt after installation, use `py` instead of `python`, or reinstall Python with **Add python.exe to PATH** ticked.

### Excel file cannot be opened

Verify that all dependencies from requirements.txt were installed successfully.
