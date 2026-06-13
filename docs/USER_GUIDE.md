# BizAssist - User Guide

BizAssist is an AI business assistant for distributors and wholesalers. Ask
questions about your business in plain language and get instant, data-backed
answers - plus alerts, insights, and actions that save you time.

---

## Getting started

1. **Log in** with your **username** and password. (New here? Use the **Sign up** tab - it asks for a username, a business name, and a password of at least 8 characters.)
2. You land on the **AI Assistant** - where you can ask questions about your
   business right away. The **Dashboard** (a snapshot of revenue, overdue
   amounts, stock, and recent activity) is one click away in the left nav.
3. Use the left navigation to move between sections (AI Assistant, Dashboard,
   Invoices, Payments, Clients, Upload, Alerts, and more).

If you have no data yet, go to **Upload** first (see below).

---

## AI Assistant (the main feature)

Open **AI Assistant** and type a question the way you'd ask a colleague. The
assistant pulls real numbers from your data - it never makes figures up.

### Instant answers (fast, no waiting)
These come back immediately:
- "What's my total revenue?"
- "Show me overdue invoices" / "Who owes me the most?"
- "How many invoices are pending?"
- "Invoice details for INV-0007"
- "Show all invoices for Nilgiris Fresh"
- "What's my best and worst selling product?"
- "Days sales outstanding (DSO)"
- "Which customers stopped buying?" (dormant customers)
- "Which customer makes me the most profit?"
- "What's low on stock?" / "What's expiring soon?"
- "Revenue in March 2026"

### Deep analysis (takes a few seconds)
For open-ended questions, the assistant studies your data and gives a plan:
- "Analyse my business and give me a growth plan"
- "Why is my cash flow tight and how do I fix it?"
- "Build me a plan to recover overdue money this month"

These end with a **"This Week: Top 3 Actions"** summary.

### Charts
Ask for a visual:
- "Show a chart of revenue by status"
- "Monthly revenue trend"
- "Top customers by revenue as a bar chart"

### Business Memory
Over time the assistant learns stable facts about your business (e.g. "Star
Bazaar usually pays late"). When memories exist, a **brain badge** appears in the
chat header showing how many are active - click it to see them. These facts make
every answer more personalised. While the AI is thinking, you'll see
"Thinking with N memories".

### Was the answer helpful?
Under each AI answer you can give a quick thumbs up / thumbs down. This feedback
helps improve future answers.

---

## Your data pages

- **Dashboard** - the at-a-glance overview of the whole business.
- **Invoices** - all invoices with totals for Paid / Pending / Overdue. Search
  and filter.
- **Payments** - payments received and outstanding.
- **Clients** - your customers, what they buy, and what they owe.
- **Database** - a raw view of all your stored records.
- **Activity** - a log of recent actions and changes.

---

## Uploading your data

Go to **Upload** to bring in your business data via CSV:
- **Invoices** - invoice_id, customer, product, amount, status, invoice_date, due_date
- **Inventory** - product_name, stock, expiry_date, supplier
- **Payments** - customer, amount, due_date, paid

The columns are matched automatically. After uploading, your numbers appear
across the Dashboard and the AI Assistant immediately.

---

## Alerts

Under **Alerts** you can turn on automatic notifications:
- **Overdue** - customers who are behind on payments
- **Low stock** - items running out
- **Expiry** - products expiring soon
- **Daily summary** - a morning overview of the business
- **Memory distillation** - the weekly job that refreshes Business Memory

You can also send a **test** of any alert to check it works before relying on it.

---

## Actions the assistant can take

Beyond answering, BizAssist can prepare real actions for you. It always shows a
**preview first and waits for your confirmation** - nothing is sent
automatically:
- **Send payment reminders** to overdue customers
- **Mark an invoice as paid**
- **Escalate** very old overdue invoices (90+ days)
- **Draft a reorder purchase order** for low-stock items
- **Email a reminder digest** to yourself

Review the preview, then confirm to proceed.

---

## Tips for best results

- Be specific - mention the customer name, invoice ID, product, or month.
- The assistant only uses numbers from your data, so keep your uploads current.
- If an answer looks off, use thumbs-down - it's recorded for improvement.
- Quick factual questions are instant; "analyse / plan / why" questions take a
  little longer because the AI is doing real analysis.

---

## Admin (for the owner/operator)

The Admin area provides operational controls:
- **Dashboard** - system overview
- **Businesses** - manage business accounts
- **Usage** - track AI token usage (useful for staying within daily limits)
- **Cache** - inspect/clear cached answers

If you hit a daily AI limit, the quick instant answers keep working - only the
deep-analysis questions pause until the limit resets (usually within an hour).
