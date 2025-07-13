import cv2
from pyzbar.pyzbar import decode
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
import requests
from datetime import datetime

# === ESP32 Configuration ===
ESP32_STREAM_URL = ""
ESP32_CONTROL_URL = ""

# === Google Sheets Setup ===
try:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        "", scope
    )
    client = gspread.authorize(creds)

    spreadsheet = client.open("Smart Labeling & Traceability")
    sheet1 = spreadsheet.sheet1
    sheet2 = spreadsheet.get_worksheet(1)

    records1 = sheet1.get_all_records()
    records2 = sheet2.get_all_records()

    print(f"✅ Loaded {len(records1)} Device Records & {len(records2)} Quality Parameters.")

    device_lookup = {
        str(row["Device ID"]).strip(): row
        for row in records1 if row.get("Device ID")
    }

    rohs_lookup = {
        str(row["Batch Id"]).strip(): row["RoHS"].strip()
        for row in records2 if row.get("Batch Id") and row.get("RoHS")
    }

    batch_details_lookup = {
        str(row["Batch Id"]).strip(): row
        for row in records2 if row.get("Batch Id")
    }

    # === Setup Sheet 3: Rejected Logs ===
    try:
        sheet3 = spreadsheet.worksheet("Rejected Logs")
    except:
        sheet3 = spreadsheet.add_worksheet(title="Rejected Logs", rows="1000", cols="30")
        headers = [
            "Timestamp", "Batch Id", "Device ID", "Factory Id", "Factory Location", "Shift",
            "Machine1", "Machine1 Time", "Machine2", "Machine2 Time",
            "Machine3", "Machine3 Time", "Alcohol Content", "Microbial Efficacy",
            "RoHS", "Quality Manager", "Tool Operator",
            "Manufacturing Date", "EXPIRY DATE"
        ]
        sheet3.append_row(headers)

    # === Setup Sheet 4: Accepted Logs ===
    try:
        sheet4 = spreadsheet.worksheet("Accepted Logs")
    except:
        sheet4 = spreadsheet.add_worksheet(title="Accepted Logs", rows="1000", cols="30")
        headers = [
            "Timestamp", "Batch Id", "Device ID", "Factory Id", "Factory Location", "Shift",
            "Machine1", "Machine1 Time", "Machine2", "Machine2 Time",
            "Machine3", "Machine3 Time", "Alcohol Content", "Microbial Efficacy",
            "RoHS", "Quality Manager", "Tool Operator",
            "Manufacturing Date", "EXPIRY DATE"
        ]
        sheet4.append_row(headers)

except Exception as e:
    print("❌ Error connecting to Google Sheets:", e)
    exit(1)

# === Start ESP32 Video Stream ===
cap = cv2.VideoCapture(ESP32_STREAM_URL)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

if not cap.isOpened():
    print("❌ Could not open ESP32-CAM stream.")
    exit(1)

cv2.namedWindow("ESP32-CAM Stream", cv2.WINDOW_NORMAL)
cv2.resizeWindow("ESP32-CAM Stream", 640, 480)

last_scanned_code = None
last_scan_time = 0
reset_delay = 3

while True:
    ret, frame = cap.read()
    if not ret:
        continue

    current_time = time.time()
    found_code = False

    for barcode in decode(frame):
        scanned_data = barcode.data.decode("utf-8").strip()

        if scanned_data != last_scanned_code or (current_time - last_scan_time) > reset_delay:
            last_scanned_code = scanned_data
            last_scan_time = current_time

            print(f"\n🔍 Scanned: {scanned_data}")
            record = device_lookup.get(scanned_data)

            if record:
                batch_id = str(record.get("Batch Id", "")).strip()
                rohs_status = rohs_lookup.get(batch_id, "Not Safe")
                batch_info = batch_details_lookup.get(batch_id, {})

                print(f"📦 Batch ID: {batch_id}, RoHS Compliance: {rohs_status}")

                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                row_data = [
                    timestamp,
                    record.get("Batch Id", "N/A"),
                    record.get("Device ID", "N/A"),
                    record.get("Factory Id", "N/A"),
                    record.get("Factory Location", "N/A"),
                    record.get("Shift", "N/A"),
                    record.get("Machine1", "N/A"),
                    record.get("Machine1 Time", "N/A"),
                    record.get("Machine2", "N/A"),
                    record.get("Machine2 Time", "N/A"),
                    record.get("Machine3", "N/A"),
                    record.get("Machine3 Time", "N/A"),
                    batch_info.get("Alcohol Content", "N/A"),
                    batch_info.get("Microbial Efficacy", "N/A"),
                    batch_info.get("RoHS", "N/A"),
                    batch_info.get("Quality Manager", "N/A"),
                    batch_info.get("Tool Operator", "N/A"),
                    batch_info.get("Manufacturing Date", "N/A"),
                    batch_info.get("EXPIRY DATE", "N/A")
                ]

                if rohs_status.lower() == "safe":
                    print("✅ ACCEPTED")
                    try:
                        sheet4.append_row(row_data)
                        print("📝 Logged acceptance to 'Accepted Logs' (Sheet 4).")
                    except Exception as e:
                        print("⚠️ Could not log to Sheet 4:", e)

                    try:
                        requests.post(ESP32_CONTROL_URL, json={
                            "status": "accepted",
                            "device_id": scanned_data,
                            "details": record
                        }, timeout=2)
                    except Exception as e:
                        print("⚠️ ESP32 Send Error:", e)

                else:
                    print("❌ REJECTED due to RoHS non-compliance")

                    print("\n📄 Device Info (Sheet 1):")
                    for field in [
                        "Batch Id", "Device ID", "Factory Id", "Factory Location", "Shift",
                        "Machine1", "Machine1 Time", "Machine2", "Machine2 Time",
                        "Machine3", "Machine3 Time"
                    ]:
                        print(f"  {field}: {record.get(field, 'N/A')}")

                    print("\n🧪 Batch Info (Sheet 2):")
                    for field in [
                        "Batch Id", "Alcohol Content", "Microbial Efficacy", "RoHS",
                        "Quality Manager", "Tool Operator", "Manufacturing Date", "EXPIRY DATE"
                    ]:
                        print(f"  {field}: {batch_info.get(field, 'N/A')}")

                    try:
                        sheet3.append_row(row_data)
                        print("📝 Logged rejection to 'Rejected Logs' (Sheet 3).")
                    except Exception as e:
                        print("⚠️ Could not log to Sheet 3:", e)

                    try:
                        requests.post(ESP32_CONTROL_URL, json={
                            "status": "rejected",
                            "device_id": scanned_data,
                            "details": {
                                "Device Info": record,
                                "Batch Info": batch_info
                            }
                        }, timeout=2)
                    except Exception as e:
                        print("⚠️ ESP32 Send Error:", e)

            else:
                print("❌ No match for Device ID")
                try:
                    requests.post(ESP32_CONTROL_URL, json={
                        "status": "rejected",
                        "device_id": scanned_data
                    }, timeout=2)
                except Exception as e:
                    print("⚠️ ESP32 Send Error:", e)

        found_code = True

    if not found_code:
        cv2.putText(frame, "Waiting for QR/Barcode...", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1)

    cv2.imshow("ESP32-CAM Stream", frame)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        print("👋 Exiting...")
        break

cap.release()
cv2.destroyAllWindows()
