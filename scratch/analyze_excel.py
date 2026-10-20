import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
import openpyxl

data_folder = 'data_folder'
for f in sorted(os.listdir(data_folder)):
    if f.endswith('.xlsx'):
        path = os.path.join(data_folder, f)
        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb.active
        print(f"File: {f}")
        print(f"  Dimensions: max_row={ws.max_row}, max_column={ws.max_column}")
        headers = [ws.cell(row=1, column=col).value for col in range(1, ws.max_column + 1)]
        # Filter trailing None headers if any
        headers = [h for h in headers if h is not None]
        print(f"  Header count: {len(headers)}")
        print(f"  Headers: {headers}")
        if ws.max_row > 1:
            sample_1 = [ws.cell(row=2, column=col).value for col in range(1, len(headers) + 1)]
            print(f"  Row 2: {sample_1}")
        if ws.max_row > 2:
            sample_2 = [ws.cell(row=3, column=col).value for col in range(1, len(headers) + 1)]
            print(f"  Row 3: {sample_2}")
        print("-" * 50)
        wb.close()
