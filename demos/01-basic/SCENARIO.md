# Demo 01 - Basic freelancer invoice

A freelance developer bills a client for a week of work plus a fixed
fee, applies sales tax and a small loyalty discount, then generates a
payment link and a PDF.

## Run it

```sh
# Create the invoice from the canned line items in items.txt
python -m invoctl --ledger /tmp/demo.json create \
  --number INV-1001 \
  --client "Acme Robotics LLC" \
  --item "Backend development (hrs):32:95.00" \
  --item "Architecture consult (flat):1:500.00" \
  --tax-rate 8.25 \
  --discount 50 \
  --due-days 14 \
  --notes "Thanks for your business!"

# Inspect it as JSON
python -m invoctl --ledger /tmp/demo.json --format json show INV-1001

# Generate a shareable payment link
python -m invoctl --ledger /tmp/demo.json pay-link INV-1001

# Render a PDF
python -m invoctl --ledger /tmp/demo.json pdf INV-1001 --out /tmp/INV-1001.pdf

# Mark it paid and view the ledger summary
python -m invoctl --ledger /tmp/demo.json status INV-1001 paid
python -m invoctl --ledger /tmp/demo.json --format json summary
```

## Expected math

- Subtotal: 32 * 95.00 + 1 * 500.00 = 3540.00
- Discount: -50.00 -> taxable 3490.00
- Tax (8.25%): 287.93
- **Total: 3777.93 USD**

The `items.txt` file lists the same line items in the
`Description:qty:unit_price` format the CLI accepts via `--item`.
