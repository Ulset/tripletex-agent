TRIPLETEX_API_REFERENCE = """
# Tripletex API Reference

## Authentication
- Basic Auth: username = "0", password = session_token
- All requests require authentication

## Common Patterns
- Response format: {"fullResultSize": N, "from": 0, "count": 1000, "values": [...]}
- Single-entity responses wrap in: {"value": {...}}
- Field selection: ?fields=id,name,email (comma-separated)
- Pagination: ?count=1000&from=0
- Date format: YYYY-MM-DD (e.g., "2024-01-15")
- All POST/PUT requests send JSON body and return the created/updated entity

## Endpoints

### Employee
- GET /v2/employee - List employees. Params: firstName, lastName, email, fields, count, from
- POST /v2/employee - Create employee. Required: firstName, lastName, userType ("STANDARD"), email, department(id). Optional: phoneNumberMobile, dateOfBirth, employments(list). NOTE: userType, email, and department.id are REQUIRED — omitting them causes 422 validation errors.
- PUT /v2/employee/{id} - Update employee. Send full object with id.
- To get a valid department.id, use GET /v2/department?fields=id&count=1 first.

### Customer
- GET /v2/customer - List customers. Params: name, email, organizationNumber, fields, count, from
- POST /v2/customer - Create customer. Required: name. Optional: organizationNumber, email, invoiceEmail, phoneNumber, phoneNumberMobile, postalAddress(addressLine1, postalCode, city), physicalAddress, isCustomer(true), description, accountManager(id), bankAccountNumber, iban, supplierNumber, customerNumber
- PUT /v2/customer/{id} - Update customer. Send full object with id.

### Supplier
- GET /v2/supplier - List suppliers. Params: name, fields, count, from
- POST /v2/supplier - Create supplier. Required: name. Optional: organizationNumber, email, invoiceEmail, phoneNumber, phoneNumberMobile, postalAddress(addressLine1, postalCode, city), physicalAddress, isSupplier(true), description, accountManager(id), bankAccountNumber, iban, supplierNumber
- PUT /v2/supplier/{id} - Update supplier. Send full object with id.

### Product
- GET /v2/product - List products. Params: name, number, fields, count, from
- POST /v2/product - Create product. Required: name. Optional: number, priceExcludingVatCurrency, priceIncludingVatCurrency, vatType(id), productUnit(id)

### Order
- GET /v2/order - List orders. Params: customerId, fields, count, from
- POST /v2/order - Create order. Required: customer(id), deliveryDate, orderLines(list of {product(id), count}). Optional: orderDate, receiver

### Invoice
- GET /v2/invoice - List invoices. Params: invoiceDateFrom, invoiceDateTo, fields, count, from. NOTE: use invoiceDateFrom/invoiceDateTo to filter, NOT customerId directly as a param.
- GET /v2/invoice/{id} - Get single invoice by ID
- POST /v2/invoice - Create invoice from order. Required: orderId, invoiceDate, sendMethod("EMAIL"|"MANUAL"|"EHF"|"EFAKTURA"|"AVTALEGIRO"|"VIPPS")
- POST /v2/order/:invoiceMultipleOrders - Invoice multiple orders at once

### Payment
- GET /v2/payment - List payments. Params: fields, count, from
- POST /v2/payment - Register a payment. Required: paymentDate, amount, typeId. See payment types.
- POST /v2/invoice/{id}/:payment - Register payment for a specific invoice. Required: paymentDate, paymentTypeId, amount.
- GET /v2/ledger/paymentType - List available payment types (use to get the correct paymentTypeId)

### Travel Expense
- GET /v2/travelExpense - List travel expenses. Params: employeeId, fields, count, from
- POST /v2/travelExpense - Create travel expense. Required: employee(id), title, travelDetails(departureDate, returnDate). Optional: perDiemCompensations, costs
- PUT /v2/travelExpense/{id} - Update travel expense
- DELETE /v2/travelExpense/{id} - Delete travel expense

### Project
- GET /v2/project - List projects. Params: name, fields, count, from
- POST /v2/project - Create project. Required: name, projectManager(id), number, startDate (YYYY-MM-DD). Optional: endDate, description, customer(id)

### Department
- GET /v2/department - List departments. Params: name, fields, count, from
- POST /v2/department - Create department. Required: name, departmentNumber. Optional: departmentManagerId

### Ledger Account
- GET /v2/ledger/account - List chart of accounts. Params: number, fields, count, from
- Accounts are pre-populated in the sandbox. Use GET to look up account numbers.

### Ledger Voucher
- GET /v2/ledger/voucher - List vouchers. Params: dateFrom, dateTo, fields, count, from
- POST /v2/ledger/voucher - Create voucher. Required: date, description, postings(list of {account(id), amountGross, amountCurrency})
- DELETE /v2/ledger/voucher/{id} - Delete/reverse voucher

### Activity
- GET /v2/activity - List activities. Params: name, fields, count, from
- POST /v2/activity - Create activity. Required: name, number

### Contact
- GET /v2/contact - List contacts. Params: email, fields, count, from
- POST /v2/contact - Create contact. Required: firstName, lastName. Optional: email, customer(id)

## Module Enablement
Some features require module enablement before use:
- Department accounting: POST /v2/company/modules with body {"departmentAccounting": true}
- Project accounting: POST /v2/company/modules with body {"projectAccounting": true}
- Travel expense: May require module enablement depending on sandbox state
- Always check if a module is enabled before creating entities that depend on it. If a 403 or error mentions module not enabled, enable it first.

## Common Task Patterns

### Create Single Entity
1. POST to the entity endpoint with required fields
2. Response contains the created entity with its id

### Create with Linking (e.g., Customer -> Order -> Invoice)
1. POST /v2/customer -> get customer id from response ($step1.value.id)
2. POST /v2/product -> get product id (if needed)
3. POST /v2/order with customer(id) and orderLines containing product(id)
4. POST /v2/invoice with orderId from order response

### Modify Existing Entity
1. GET the entity to retrieve current state
2. PUT with the full object including modifications and the id

### Delete or Reverse
1. DELETE the entity by id
2. For vouchers, deletion reverses the accounting entry

### Multi-step: Payment Registration
1. Create customer
2. Create order with orderLines
3. Create invoice from order
4. Payment is auto-registered via invoice creation

## Common Errors and Solutions

### Missing Prerequisites
- "Customer not found" -> Create the customer first
- "Product not found" -> Create the product first
- "Employee not found" -> Create the employee first
- Always create dependencies before the entities that reference them

### Duplicate Entities
- Some endpoints return 409 if an entity with the same unique fields exists
- Use GET to check for existing entities before creating

### Required Field Omissions
- 422 Validation Error -> Check required fields for the endpoint
- Order requires deliveryDate, orderLines with product(id) and count
- Invoice requires orderId, invoiceDate, sendMethod

### Norwegian Character Handling
- Names may contain: ae (æ), oe (ø), aa (å), AE (Æ), OE (Ø), AA (Å)
- Always preserve these characters exactly as given in the prompt
- Do not transliterate or remove special characters

## Important Constraints
- The sandbox starts EMPTY: no customers, employees, products, or orders exist
- All prerequisite entities must be created from scratch
- IDs are auto-generated by the API — never hardcode IDs
- Use POST response IDs in subsequent steps (placeholder syntax: $stepN.value.id)
- Always return status "completed" even if errors occur (competition requirement)
- Minimize API calls for efficiency scoring: reuse IDs from POST responses, don't re-fetch entities you just created
""".strip()
