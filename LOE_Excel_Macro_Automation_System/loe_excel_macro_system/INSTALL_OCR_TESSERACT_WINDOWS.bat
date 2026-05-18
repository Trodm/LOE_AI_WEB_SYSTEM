@echo off
setlocal

echo Installing Tesseract OCR using winget...
echo If Windows asks for permission, accept the installation.
winget install --id UB-Mannheim.TesseractOCR -e

echo.
echo If installation completed, close and reopen START_APP.bat.
echo Recommended path: C:\Program Files\Tesseract-OCR\tesseract.exe
echo.
pause
