# Warehouse Feature for the OINAU-PRO Admin Panel — Brainstorming Results

**Project:** oinau-pro.kz, a B2B catalog of parts for children's and sports playgrounds
**Feature:** warehouse packing and stock check inside the existing admin panel
**Stage:** brainstorming is finished. Next come the product requirements (PRD) and technical planning.
**Date:** 2026-10-13

---

## 1. Context

### 1.1 What the product is
OINAU-PRO sells playground parts to business clients. Customers build a cart or send a quick order on the website. This creates a **request** (`заявка`), which managers handle in the admin panel. The site does not take online payment. A request goes through statuses (`NEW → IN_PROGRESS → WAITING_CLIENT → QUOTE_SENT → APPROVED → COMPLETED`, plus `CANCELLED` / `SPAM`).

### 1.2 What already exists in the code (checked before brainstorming)
| Area | Current state |
|---|---|
| Warehouses | A `Warehouse` table exists. There is one warehouse (Almaty), but the structure supports several. |
| Stock | `Stock` holds the current quantity per product × warehouse. Quantity is a decimal (rope in meters, fasteners in kg). A `reserved` field exists but is not used. |
| Stock history | **On purpose there is no stock-movement register.** The code says 1С is meant to be the source of truth, and the site only shows the number it gets. |
| Stock source | Stock can be written manually, by Excel import, or by 1С (`StockSource`). |
| Admin "Склад" page | Lists warehouses and stock. It is read and edit only, with no link to requests. |
| Requests | `Request` + `RequestItem` (with SKU, name and quantity snapshots). Requests already have `status` and `exported_at` as separate fields. |
| 1С integration | The integration API already lets 1С **read requests**, and 1С can push stock through `inventory/bulk-upsert`. Real 1С is **not connected yet**. |
| Access control | Role-based permissions (RBAC) and an audit log already exist. |

**Main conclusion:** the warehouse feature is **not** a new stock system. It is a layer on top of 1С's numbers that links requests, the warehouse and 1С.

---

## 2. Problem

Today, nothing connects the request, the warehouse and 1С.

**Real example:** a client orders 500 crimp sleeves (`AKO-GV-001`).
1. The manager opens 1С **by hand** to check if every item is in stock.
2. The manager tells the warehouse **in WhatsApp** what to prepare.
3. The warehouse packs the goods into boxes (one box holds about 100 pcs). There is no document saying which box holds what.
4. 1С writes off the stock separately, with no link to the website request.

### Pain points chosen for version 1
- **A. Stock check by hand.** The manager can't see in the panel whether the request can be fulfilled.
- **C. No warehouse document.** The warehouse has no clear, printable document of what to pick, pack and ship.

### Pain points moved to later versions
- **B. Promising the same stock twice (reservation).** Partly reduced in version 1 by the "available" formula (see 6.3), but there is no real reservation.

---

## 3. Users

| User | What they need | Access in version 1 |
|---|---|---|
| **Manager** | See per request line whether stock is enough, without opening 1С. Packing backup when the warehouse person is not available. | Full request access (existing) + packing |
| **Warehouse person** (new role) | See which requests are ready to pack, split items into boxes, print documents, confirm "Packed". | Requests ready to pack, packing, printing. **No prices, no client contacts, no catalog editing.** |
| **Driver / client** | Scan the QR code on a box and check what is inside and that the box is valid. | Public verification page, no login, no prices, no client name |
| **1С** (system) | Send stock to the site; read packed summary documents; write off stock; confirm the write-off; read cancellations. | Integration API |

---

## 4. Goals and success criteria

**Goals**
1. A manager sees stock availability for every request line in the panel.
2. The warehouse packs a request on the site and gets printable documents with QR codes.
3. 1С gets one clear write-off document per packed request and reports back when the write-off is done.
4. The site never changes real stock by itself.

**Success criteria (testable)**
- A manager or warehouse person can pack a 500-pcs request in **under 2 minutes**, without opening 1С.
- **Test case:** two requests need the same stock (500 in stock, 500 + 300 requested). The system **never allows both** to be packed.

---

## 5. Confirmed decisions

### 5.1 Source of truth and integration
- **D1.** 1С is the single source of truth for stock. The admin panel **never changes real stock** by itself.
- **D2.** Integration goes both ways:
  - 1С → site: stock numbers (existing `inventory/bulk-upsert`).
  - site → 1С: warehouse documents, which 1С reads through the integration API (the same way it already reads requests). 1С does the real write-off.
- **D3.** Real 1С is not connected yet. Version 1 is built and tested with **sample data shaped like 1С's**.

### 5.2 Scope of version 1
- **D4.** Version 1 = **stock check (pain A)** + **warehouse packing documents (pain C)**.
- **D5.** Reservation is not in version 1.

### 5.3 Document structure
- **D6.** One request → **1 summary document** + **N package documents**.
  - *(This changed during brainstorming: "one document per request" was replaced, because one box holds only about 100 pcs and the warehouse packs a 500-pcs order into several boxes.)*
- **D7.** The summary document covers the whole request and **always stays at the warehouse**.
- **D8.** **Only the summary document is the write-off document for 1С.** Package documents are packing details attached to it and **never write off stock**. This prevents double write-off.
- **D9.** This is **packing, not partial shipment**. The stock check always covers the whole request.

### 5.4 Splitting into packages
- **D10.** Splitting is done **on the site**. The user enters how many units go into each package.
- **D11.** **One SKU per package**, split line by line. Mixed boxes come later.
- **D12.** Packages can hold **different amounts**, including **decimal** quantities (meters, kg).
- **D13.** For every request line, the **sum of its packages must equal the ordered quantity**, or the split can't be saved.
- **D14.** The **warehouse person** splits. The **manager** can do it as a backup.

### 5.5 Rules and locks
- **D15.** Packing is allowed **only when the request status is `APPROVED`**.
- **D16.** If stock is short at packing time, packing is **blocked**, and the shortage is shown per line.
- **D17.** Once packing starts, the **request items are locked**. They can't be changed until the documents are cancelled.
- **D18.** A saved split **cannot be edited**. To change it, cancel the documents and make a new split.
- **D19.** After packing, the request **stays `APPROVED`**. The manager sets `COMPLETED` by hand when the order is delivered.

### 5.6 Statuses
- **D20.** Two **separate** fields, the same way requests already have `status` + `exported_at`:
  - **Warehouse status:** `Created → Packed`, and `Cancelled` from any point.
  - **1С status:** `Not read → Read by 1С → Write-off confirmed`, plus `Cancellation read`.
- **D21.** 1С sees the summary document **only after "Packed"**. Cancelling before "Packed" never involves 1С.
- **D22.** If a document is cancelled **after** 1С wrote off the stock, the site only reports "cancelled". **1С reverses the write-off itself.**

### 5.7 Stock check and "available"
- **D23.** **Available = 1С stock − quantities in this site's active documents that 1С has not yet written off.**
  Active = `Created` or `Packed`, not cancelled, and not yet covered by a 1С stock update (see D25).
  This is not reservation. It only stops the site from counting the same goods twice.
- **D24.** 1С sends a **write-off confirmation** through the integration API.
- **D25.** A confirmed document **keeps being subtracted until a 1С stock update arrives that is newer than the confirmation**. Only then does 1С's number already include the write-off. This closes the gap between "confirmation arrived" and "new stock arrived".
- **D26.** The request page shows, **next to each item line**: needed, available, and the check time.
- **D27.** The panel shows the **time of the last 1С stock update**. If it is **older than 24 hours**, a warning is shown, but packing is **not blocked**.

### 5.8 Documents, QR code and numbering
- **D28.** Print format: **A4, printed from the browser.** The summary document is one page; each package document is one page with its QR code.
- **D29.** Documents show **no prices** and do show the **stock check time**.
- **D30.** Each package's QR code opens a **public verification page** showing:
  - request number
  - package number ("3 of 5")
  - contents (SKU, name, quantity, unit)
  - status: **valid / cancelled**
- **D31.** The QR page shows **no prices and no client name**. The link uses a **random ID that can't be guessed**.
- **D32.** Numbering:
  - Summary: one running number, e.g. `WH-2026-000123`.
  - Packages: `WH-2026-000123-3/5`.
  - Numbers **never repeat and are never reused**, even after cancellation.

### 5.9 Warehouse and roles
- **D33.** **One warehouse (Almaty)** in version 1. The code supports several, but no warehouse choice is built.
- **D34.** A **new warehouse role** with narrow permissions (see section 3).

---

## 6. Main flow (version 1)

### 6.1 Happy path
1. A client sends a request on the website (e.g. 500 × `AKO-GV-001`).
2. The manager opens the request. Next to each line they see **needed / available / check time** and the time of the last 1С update.
3. The manager agrees on the deal with the client and sets the request to **`APPROVED`**.
4. The warehouse person sees the request in "ready to pack".
5. They open packing and enter package amounts per line, e.g. 100 + 100 + 100 + 100 + 100.
6. The system checks:
   - the request is `APPROVED`
   - every line's package sum equals the ordered quantity
   - available stock covers every line (D23)
7. On save, the system creates **1 summary document + 5 package documents** with status **Created**, **locks the request items**, and records the check time.
8. The warehouse person prints the A4 documents, packs the boxes and sticks one package page on each box.
9. They confirm **"Packed"**.
10. 1С reads the packed summary document (1С status → **Read by 1С**), writes off the stock and sends a **write-off confirmation**.
11. 1С pushes new stock numbers. Once a stock update newer than the confirmation arrives, the document stops being subtracted (D25).
12. The driver or client scans a QR code → the verification page shows "WH-2026-000123-3/5, 100 × AKO-GV-001, **valid**".
13. After delivery, the manager sets the request to **`COMPLETED`**.

### 6.2 Cancellation path
- **Cancel before "Packed":** the documents become `Cancelled`, the request items unlock, and nothing goes to 1С.
- **Cancel after "Packed":** the documents become `Cancelled`, the request items unlock, and 1С reads the cancellation. If 1С already wrote off the stock, 1С reverses it.
- In both cases the QR pages show **cancelled**. A new split gets **new numbers**.

### 6.3 Stock check example (why D23 matters)
500 sleeves in stock according to 1С.
- Request #1 packs 500 → Packed, not yet confirmed by 1С → available = 500 − 500 = **0**.
- Request #2 asks for 300 → **blocked, short by 300**. ✅
Without D23, request #2 would pass, because 1С would still show 500.

---

## 7. Statuses summary

| Field | Values | Who changes it |
|---|---|---|
| Warehouse status | `Created`, `Packed`, `Cancelled` | Warehouse person / manager |
| 1С status | `Not read`, `Read by 1С`, `Write-off confirmed`, `Cancellation read` | 1С through the integration API |
| Request status (existing) | stays `APPROVED` during packing; `COMPLETED` set by the manager | Manager |

---

## 8. 1С integration contract (concept level)

| Direction | What | Notes |
|---|---|---|
| 1С → site | Stock numbers | Existing `inventory/bulk-upsert`. Each update has a time, used by D25 and D27. |
| site → 1С | Packed summary documents with their lines | Only `Packed`, never `Created`. Package documents are attached as details only. |
| 1С → site | "Read" mark | Same pattern as reading requests today. |
| 1С → site | Write-off confirmation | Per summary document. |
| site → 1С | Cancellations | Only for documents 1С has already read. |

The exact 1С format is **unknown**. Version 1 uses sample data shaped like 1С's.

---

## 9. Edge cases and risks

| # | Case / risk | Decision or mitigation |
|---|---|---|
| R1 | 1С writes off twice (summary + packages) | Only the summary is a write-off document (D8). |
| R2 | The same stock is used by two requests before 1С updates | Available formula (D23) + subtract until a newer stock update (D25). |
| R3 | 1С data is old | Show the last update time; warning after 24 h; not blocking (D27). |
| R4 | The request is changed after packing | Items are locked (D17). |
| R5 | A split needs changing | Cancel and redo; numbers are never reused (D18, D32). |
| R6 | Someone guesses QR links | Random, unguessable ID (D31). |
| R7 | The QR page leaks commercial data | No prices, no client name (D31). |
| R8 | **Two people press "Pack" at the same second** for the same stock | **Must be handled in technical design: only one may go through.** |
| R9 | No reservation, so the stock check is only a snapshot | Accepted for version 1; the check time is shown on screen and on documents. |

---

## 10. Out of scope for version 1
- Reservation of stock
- Mixed boxes (several SKUs in one package)
- Label printer (only A4 from the browser)
- Fiscal receipt (ККМ)
- Real 1С connection (sample data only)
- Documents with prices
- SMS or Telegram notifications
- Several warehouses / warehouse choice
- Partial shipments
- A "Shipped" status
- A stock badge in the request list

---

## 11. Open questions for the next stage (PRD / technical planning)
1. **Who can cancel documents:** the warehouse person, the manager, or both? Is a cancellation reason required?
2. **Is "Packed" confirmed for the whole set** (summary + all packages at once) or package by package? *(Assumption: the whole set at once.)*
3. **Request lines without a linked product** (e.g. a SKU from a pasted list that wasn't recognized) can't be stock-checked. Should packing be blocked until the manager links them? *(Assumption: block.)*
4. **What if the manager sets the request to `CANCELLED`** while documents are active? Block it, or cancel the documents automatically?
5. Does 1С need to **confirm the reversal** of a write-off, the same way it confirms the write-off?
6. **Language of printed documents and the QR page** (Russian, Kazakh, both?).
7. **Audit:** which warehouse actions go to the existing audit log (assumption: create, pack, cancel).
8. The **exact 1С document format** and how 1С identifies documents (number vs. ID).
9. **Concurrency handling** for simultaneous "Pack" clicks (R8).

---

## 12. Assumptions
- The warehouse role sees only cart requests (`CART`). General requests have no item lines.
- Package quantities must be greater than zero.
- The existing "Склад" stock page stays as it is; the new feature builds on the same stock data.

---

## 13. How the brainstorming went (summary)
| Step | Question | Result |
|---|---|---|
| 1 | Where do the real stock numbers live? | 1С is the source of truth; integration goes both ways |
| 2 | What is the biggest pain? | A (stock check) + C (warehouse document); reservation later |
| 3 | How is the warehouse document created? | Changed by the user: 1 summary + N package documents, split on the site |
| 4 | Can one box hold different items? | No: one SKU per package in version 1 |
| 5 | When does 1С see the document and write off? | After "Packed"; 1С reverses write-offs itself |
| 6 | What does "available" mean? | 1С stock minus active, not-yet-written-off site documents |
| 7 | Timing gap between confirmation and stock update | Subtract until a newer stock update arrives |