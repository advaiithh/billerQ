/**
 * BillerQ AI Copilot Widget v5.0 — DOM-First Intelligence
 * =========================================================
 *
 * Priority Order (no model unless absolutely necessary):
 *   1. Deep DOM scrape → answer from visible page data (INSTANT)
 *   2. METRIC_ALIASES  → map question to scraped value (INSTANT)
 *   3. PAGE_MAP        → navigation (INSTANT)
 *   4. SOP_WORKFLOWS   → step-by-step guides (INSTANT)
 *   5. Backend + model → complex analysis, customer search (LAST RESORT)
 *
 * Response format (always):
 *   [Full Data Summary]
 *   [Actionable Insight]
 *   [Redirect Link] ← LAST, never first
 *
 * Backend: http://localhost:8001 (FastAPI)
 */

(function () {
  "use strict";

  // ─── CONFIG ────────────────────────────────────────────────────────────────
  const API_BASE        = "http://localhost:8001";
  const WIDGET_ID       = "billerq-copilot-root";
  const CRYPTO_KEY      = "your-secret-key";
  const MOUNT_DELAY_MS  = 1800;
  const SCRAPE_INTERVAL = 8000; // Re-scrape DOM every 8s

  // ─── PAGE MAP ─────────────────────────────────────────────────────────────
  const PAGE_MAP = {
    "dashboard":              "/dashboard/default",
    "customers":              "/customers/customer",
    "add_customer":           "/customers/customer-add",
    "edit_customer":          "/customers/customer-edit",
    "customer_archive":       "/customers/customer-archive",
    "stb_modem":              "/customers/stb-modem",
    "wallet":                 "/customers/wallet",
    "payments":               "/payment/quick-pay",
    "invoices":               "/billing/invoice",
    "invoice_cancel":         "/billing/invoice-cancel",
    "subscriptions":          "/billing/subscription",
    "subscription_add":       "/billing/subscription-add",
    "activate_subscription":  "/billing/activate-subscription",
    "recurring":              "/billing/recurring",
    "orders":                 "/billing/order-add",
    "complaints":             "/complaints",
    "complaints_add":         "/complaints-add",
    "complaints_edit":        "/complaints-edit",
    "collections":            "/report/payment-collection",
    "reports":                "/report/payment-collection",
    "payment_due":            "/report/payment-due",
    "unpaid_customers":       "/report/unpaid-customer",
    "expense_report":         "/report/expense-summary",
    "income_report":          "/report/income-summary",
    "tax_report":             "/report/tax-report",
    "addon_report":           "/report/addon-summary",
    "subscription_report":    "/report/subscription-summary",
    "sms_logs":               "/report/sms-message-logs",
    "online_payment":         "/report/online-payment",
    "wallet_report":          "/report/wallet-balance",
    "settings":               "/settings/area",
    "settings_area":          "/settings/area",
    "settings_categories":    "/settings/categories",
    "settings_payment":       "/settings/payment",
    "settings_tax":           "/settings/tax-group",
    "settings_message":       "/settings/custom-message",
    "users":                  "/menu/user",
    "roles":                  "/menu/role",
  };

  const NAV_ALIASES = {
    "dashboard": "dashboard",        "home": "dashboard",
    "customer": "customers",         "customers": "customers",
    "payment": "payments",           "payments": "payments",
    "quick pay": "payments",         "invoice": "invoices",
    "invoices": "invoices",          "billing": "invoices",
    "subscription": "subscriptions", "subscriptions": "subscriptions",
    "complaint": "complaints",       "complaints": "complaints",
    "ticket": "complaints",          "collection": "collections",
    "collections": "collections",    "report": "reports",
    "reports": "reports",            "wallet": "wallet",
    "settings": "settings",         "users": "users",
    "staff": "users",                "roles": "roles",
    "add customer": "add_customer",  "new customer": "add_customer",
    "add complaint": "complaints_add","new complaint": "complaints_add",
    "add subscription": "subscription_add","new subscription": "subscription_add",
    "payment collection": "collections","payment due": "payment_due",
    "unpaid": "unpaid_customers",    "expense": "expense_report",
    "income": "income_report",       "tax": "tax_report",
    "sms": "sms_logs",               "online payment": "online_payment",
    "wallet balance": "wallet_report","wallet report": "wallet_report",
  };

  // ─── METRIC ALIASES ────────────────────────────────────────────────────────
  // Maps natural language → scraper key
  const METRIC_ALIASES = {
    "active customer": "active_customers",      "active customers": "active_customers",
    "inactive customer": "inactive_customers",  "inactive customers": "inactive_customers",
    "total customer": "total_customers",        "total customers": "total_customers",
    "how many customer": "total_customers",     "how many customers": "total_customers",
    "today collection": "today_collection",     "today's collection": "today_collection",
    "collection today": "today_collection",     "how much collection": "today_collection",
    "collection this month": "monthly_collection","monthly collection": "monthly_collection",
    "this month collection": "monthly_collection",
    "pending amount": "pending_amount",         "pending payment": "pending_amount",
    "due amount": "pending_amount",             "how much pending": "pending_amount",
    "open complaint": "open_complaints",        "open complaints": "open_complaints",
    "how many complaint": "open_complaints",    "complaints count": "open_complaints",
    "active subscription": "active_subscriptions","active subscriptions": "active_subscriptions",
    "how many subscription": "active_subscriptions",
    "outstanding": "total_outstanding",         "outstanding amount": "total_outstanding",
    "total outstanding": "total_outstanding",   "unpaid amount": "total_outstanding",
    "overdue": "overdue_customers",             "overdue customer": "overdue_customers",
    "overdue customers": "overdue_customers",
    "today payment": "today_payments",          "today's payment": "today_payments",
    "payments today": "today_payments",
    "invoice amount": "invoice_amount",         "total invoice": "invoice_amount",
    "collection this month": "monthly_collection",
    "revenue": "total_revenue",                 "total revenue": "total_revenue",
    "due invoice": "due_invoice",               "invoice due": "due_invoice",
  };

  // ─── WORKFLOW SOPs ─────────────────────────────────────────────────────────
  const WORKFLOW_SOPS = {
    assign_technician: {
      title: "Assign a Technician to a Complaint",
      steps: ["Go to **Complaints** in the sidebar.", "Find and open the complaint.", "Click **Assign Technician** and select the technician.", "Click **Save** — customer gets notified automatically."],
      page: "complaints",
    },
    generate_invoice: {
      title: "Generate an Invoice",
      steps: ["Go to **Billing → Invoices**.", "Click **Add Invoice**.", "Select customer, add items, apply taxes/discounts.", "Click **Save** — you can print or email from there."],
      page: "invoices",
    },
    close_complaint: {
      title: "Close / Resolve a Complaint",
      steps: ["Go to **Complaints** in the sidebar.", "Open the resolved complaint.", "Change status to **Resolved** and add resolution notes.", "Click **Save** — customer is notified automatically."],
      page: "complaints",
    },
    add_customer: {
      title: "Add a New Customer",
      steps: ["Go to **Customers → Add Customer**.", "Fill in name, phone, address, area.", "Select subscription plan and STB/Modem details.", "Click **Save**."],
      page: "add_customer",
    },
    process_payment: {
      title: "Process a Payment",
      steps: ["Go to **Payments → Quick Pay**.", "Search for the customer.", "Enter amount, select payment method (Cash/UPI/Card).", "Click **Submit** — receipt auto-generated."],
      page: "payments",
    },
    create_subscription: {
      title: "Create a Subscription",
      steps: ["Go to **Billing → Subscriptions → Add Subscription**.", "Select customer and plan.", "Set billing cycle and start date.", "Click **Save** to activate."],
      page: "subscription_add",
    },
    activate_customer: {
      title: "Activate a Customer",
      steps: ["Go to **Billing → Activate Subscription**.", "Search for the customer.", "Select the subscription to activate.", "Confirm date and click **Activate**."],
      page: "activate_subscription",
    },
    generate_report: {
      title: "Generate a Collection Report",
      steps: ["Go to **Reports → Payment Collection**.", "Select the date range.", "Filter by area or agent if needed.", "Click **Generate** then export as Excel or PDF."],
      page: "collections",
    },
    add_complaint: {
      title: "Log a New Complaint",
      steps: ["Go to **Complaints → Add Complaint**.", "Search and select the customer.", "Select category, priority, describe the issue.", "Assign technician if available and click **Save**."],
      page: "complaints_add",
    },
  };

  const WORKFLOW_TRIGGERS = {
    assign_technician:  ["assign technician", "assign engineer", "allocate technician"],
    generate_invoice:   ["generate invoice", "create invoice", "make invoice", "new invoice", "how to invoice"],
    close_complaint:    ["close complaint", "resolve complaint", "mark resolved", "close ticket"],
    add_customer:       ["add customer", "new customer", "create customer", "register customer"],
    process_payment:    ["process payment", "record payment", "collect payment", "how to pay", "accept payment"],
    create_subscription:["create subscription", "add subscription", "new subscription", "make subscription"],
    activate_customer:  ["activate customer", "activate account", "activate subscription"],
    generate_report:    ["generate report", "create report", "export report", "download report"],
    add_complaint:      ["add complaint", "log complaint", "new complaint", "raise complaint", "file complaint"],
  };

  // ─── DOM SCRAPERS ─────────────────────────────────────────────────────────
  // Page-specific scrapers that read directly from React-rendered DOM

  const scraped = {}; // Live cache — updated every SCRAPE_INTERVAL

  function num(str) {
    if (!str) return null;
    const n = parseFloat(str.replace(/[₹,\s]/g, ""));
    return isNaN(n) ? null : n;
  }

  function textOf(el) {
    return el ? el.innerText.trim() : "";
  }

  function findByText(selector, text) {
    return Array.from(document.querySelectorAll(selector)).find(el =>
      el.innerText.toLowerCase().includes(text.toLowerCase())
    );
  }

  function scrapeAll() {
    const path = window.location.pathname;
    const data = {};

    try {
      // ── Universal: read ALL numeric cards on page ──────────────────────────
      // BillerQ uses stat cards with a number + label pattern
      document.querySelectorAll("[class*='card'], [class*='stat'], [class*='count'], [class*='metric']").forEach(el => {
        const text = el.innerText;
        const lines = text.split("\n").map(l => l.trim()).filter(Boolean);
        // Look for pairs: number, then label
        lines.forEach((line, i) => {
          const n = num(line);
          if (n !== null && lines[i + 1]) {
            const label = lines[i + 1].toLowerCase();
            if (label.includes("active") && label.includes("customer")) data.active_customers = n;
            else if (label.includes("inactive") && label.includes("customer")) data.inactive_customers = n;
            else if (label.includes("total") && label.includes("customer")) data.total_customers = n;
            else if (label.includes("complaint")) data.open_complaints = n;
            else if (label.includes("subscription")) data.active_subscriptions = n;
          }
        });
      });

      // ── DASHBOARD PAGE ─────────────────────────────────────────────────────
      if (path.includes("dashboard")) {
        const fullText = document.body.innerText;

        // Revenue Meter
        const invoiceMatch = fullText.match(/Invoice\s*[\u20B9Rs.]*\s*([\d,]+\.?\d*)/i);
        const dueMatch     = fullText.match(/Due\s*[\u20B9Rs.]*\s*([\d,]+\.?\d*)/i);
        const collMatch    = fullText.match(/Collection\s*[\u20B9Rs.]*\s*([\d,]+\.?\d*)/i);
        if (invoiceMatch) data.invoice_amount  = num(invoiceMatch[1]);
        if (dueMatch)     data.due_invoice     = num(dueMatch[1]);
        if (collMatch)    data.monthly_collection = num(collMatch[1]);

        // Collection Meter (This Month section)
        const thisMonthSection = fullText.match(/This Month[\s\S]{0,300}?Collection\s*[\u20B9Rs.]*\s*([\d,]+\.?\d*)/i);
        if (thisMonthSection) data.today_collection = num(thisMonthSection[1]);

        // Connections
        const iptvMatch = fullText.match(/IP TV[\s\S]{0,50}?(\d+)\s*Connections/i);
        const ottMatch  = fullText.match(/OTT[\s\S]{0,50}?(\d+)\s*Connections/i);
        if (iptvMatch) data.iptv_connections = Number(iptvMatch[1]);
        if (ottMatch)  data.ott_connections  = Number(ottMatch[1]);

        // Revenue %
        const pctMatch = fullText.match(/(\d+\.?\d*)\s*%/);
        if (pctMatch) data.revenue_pct = Number(pctMatch[1]);

        // Recurring invoices
        const recurringMatch = fullText.match(/Recurring for all Invoices\s*\((\d+)\)/i);
        if (recurringMatch) data.recurring_invoices = Number(recurringMatch[1]);

        // Monthly Overview amount
        const overviewMatch = fullText.match(/Monthly Overview[\s\S]{0,80}?[\u20B9Rs.]*\s*([\d,]+\.?\d*)/i);
        if (overviewMatch) data.monthly_overview = num(overviewMatch[1]);

        // Notification badge (complaints/alerts)
        const badge = document.querySelector("[class*='badge'], [class*='notification']");
        if (badge) {
          const bNum = num(badge.innerText);
          if (bNum !== null) data.notification_count = bNum;
        }
      }

      // ── CUSTOMERS PAGE ─────────────────────────────────────────────────────
      if (path.includes("customer")) {
        const fullText = document.body.innerText;
        const rows = document.querySelectorAll("table tbody tr, [class*='table'] [class*='row']");
        data.customer_table_rows = rows.length;

        // Status breakdown from filter pills / tabs
        const activeTab = findByText("[class*='tab'], [class*='pill'], [class*='filter']", "active");
        if (activeTab) {
          const countInTab = activeTab.innerText.match(/(\d+)/);
          if (countInTab) data.active_customers = Number(countInTab[1]);
        }

        // Total from pagination
        const totalMatch = fullText.match(/Total[:\s]*([\d,]+)/i) || fullText.match(/([\d,]+)\s*records/i);
        if (totalMatch) data.total_customers = num(totalMatch[1]);
      }

      // ── PAYMENTS PAGE ──────────────────────────────────────────────────────
      if (path.includes("payment") || path.includes("collection")) {
        const fullText = document.body.innerText;
        const totalMatch  = fullText.match(/Total[:\s]*[\u20B9Rs.]*\s*([\d,]+\.?\d*)/i);
        const countMatch  = fullText.match(/([\d,]+)\s*(?:records|payments|transactions)/i);
        if (totalMatch) data.collection_total = num(totalMatch[1]);
        if (countMatch) data.payment_count    = num(countMatch[1]);

        // Table rows
        const rows = document.querySelectorAll("table tbody tr");
        data.payment_table_rows = rows.length;

        // Extract table summary if visible
        const tableData = [];
        rows.forEach(row => {
          const cells = Array.from(row.querySelectorAll("td")).map(td => td.innerText.trim());
          if (cells.length > 2) tableData.push(cells);
        });
        if (tableData.length > 0) data.payment_rows_sample = tableData.slice(0, 5);
      }

      // ── COMPLAINTS PAGE ────────────────────────────────────────────────────
      if (path.includes("complaint")) {
        const fullText = document.body.innerText;
        const openMatch   = fullText.match(/Open[:\s]*(\d+)/i);
        const closedMatch = fullText.match(/Closed[:\s]*(\d+)/i);
        const totalMatch  = fullText.match(/Total[:\s]*(\d+)/i);
        if (openMatch)   data.open_complaints   = Number(openMatch[1]);
        if (closedMatch) data.closed_complaints = Number(closedMatch[1]);
        if (totalMatch)  data.total_complaints  = Number(totalMatch[1]);

        const rows = document.querySelectorAll("table tbody tr");
        data.complaint_table_rows = rows.length;
      }

      // ── INVOICES / BILLING PAGE ────────────────────────────────────────────
      if (path.includes("invoice") || path.includes("billing")) {
        const fullText = document.body.innerText;
        const totalMatch = fullText.match(/Total[:\s]*[\u20B9Rs.]*\s*([\d,]+\.?\d*)/i);
        if (totalMatch) data.invoice_total = num(totalMatch[1]);
        const rows = document.querySelectorAll("table tbody tr");
        data.invoice_table_rows = rows.length;
      }

      // ── REPORTS PAGE ───────────────────────────────────────────────────────
      if (path.includes("report")) {
        const fullText = document.body.innerText;
        const amountMatches = fullText.match(/[\u20B9Rs.]*\s*([\d,]+\.?\d*)/g) || [];
        const amounts = amountMatches.map(m => num(m)).filter(n => n !== null && n > 0);
        if (amounts.length > 0) data.report_amounts = amounts.slice(0, 10);

        const dateMatch = fullText.match(/(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4})/g);
        if (dateMatch) data.report_dates = dateMatch.slice(0, 4);
      }

      // ── ALWAYS: read header / top-bar stats ────────────────────────────────
      // BillerQ's top bar often has quick stats
      const header = document.querySelector("header, nav, [class*='header'], [class*='topbar']");
      if (header) {
        const headerText = header.innerText;
        const numMatches = headerText.match(/[\d,]+/g) || [];
        if (numMatches[0]) data.header_stat_1 = Number(numMatches[0].replace(/,/g, ""));
      }

    } catch (e) {
      // Silent — scraping should never crash the widget
    }

    // Merge with any prev data (keep best values)
    Object.assign(scraped, data);
    window.billerqScraped = scraped;
    return scraped;
  }

  // ─── AUTH ─────────────────────────────────────────────────────────────────
  function getLoginData() {
    try {
      const raw = localStorage.getItem("login");
      if (!raw) return null;
      try { const p = JSON.parse(raw); if (p && p.userToken) return p; } catch (_) {}
      const CJS = window.CryptoJS || window._bqCryptoJS;
      if (CJS) {
        try {
          const b = CJS.AES.decrypt(raw, CRYPTO_KEY);
          const p = JSON.parse(b.toString(CJS.enc.Utf8));
          if (p && p.userToken) return p;
        } catch (_) {}
      }
      return null;
    } catch (_) { return null; }
  }

  function isLoggedIn() {
    try { const r = localStorage.getItem("login"); return !!r && r.length > 10; } catch (_) { return false; }
  }

  function getUserName()  { const d = getLoginData(); return d ? (d.name || d.userName || "User").split(" ")[0] : "User"; }
  function getUserToken() { const d = getLoginData(); return d ? (d.userToken || null) : null; }
  function getCompanyId() { const d = getLoginData(); return d ? (d.company_id || d.companyId || null) : null; }
  function getUserRole()  { const d = getLoginData(); return d ? (d.role || d.userRole || null) : null; }

  function loadCryptoJS() {
    if (window.CryptoJS || window._bqCryptoJS) return;
    const s = document.createElement("script");
    s.src = "https://cdnjs.cloudflare.com/ajax/libs/crypto-js/4.2.0/crypto-js.min.js";
    s.onload = () => { window._bqCryptoJS = window.CryptoJS; };
    document.head.appendChild(s);
  }

  // ─── FORMATTERS ───────────────────────────────────────────────────────────
  function fmt(val, type) {
    const n = Number(val);
    if (isNaN(n)) return String(val);
    if (type === "currency") {
      if (n >= 10000000) return `₹${(n / 10000000).toFixed(2)} Cr`;
      if (n >= 100000)   return `₹${(n / 100000).toFixed(2)} Lakh`;
      if (n >= 1000)     return `₹${n.toLocaleString("en-IN")}`;
      return `₹${n.toFixed(2)}`;
    }
    return n.toLocaleString("en-IN");
  }

  function pct(val) {
    const n = Number(val);
    return isNaN(n) ? "—" : `${n.toFixed(1)}%`;
  }

  // ─── METRIC META ───────────────────────────────────────────────────────────
  const METRIC_META = {
    active_customers:     { label: "Active customers",      icon: "✅", type: "number",   page: "customers" },
    inactive_customers:   { label: "Inactive customers",    icon: "🔴", type: "number",   page: "customers" },
    total_customers:      { label: "Total customers",       icon: "👥", type: "number",   page: "customers" },
    today_collection:     { label: "Today's collection",    icon: "💰", type: "currency", page: "collections" },
    monthly_collection:   { label: "Monthly collection",    icon: "📊", type: "currency", page: "collections" },
    pending_amount:       { label: "Pending amount",        icon: "⏳", type: "currency", page: "payment_due" },
    open_complaints:      { label: "Open complaints",       icon: "🔧", type: "number",   page: "complaints" },
    closed_complaints:    { label: "Closed complaints",     icon: "✔️", type: "number",   page: "complaints" },
    active_subscriptions: { label: "Active subscriptions",  icon: "📋", type: "number",   page: "subscriptions" },
    total_outstanding:    { label: "Total outstanding",     icon: "💳", type: "currency", page: "payment_due" },
    overdue_customers:    { label: "Overdue customers",     icon: "⚠️", type: "number",   page: "payment_due" },
    today_payments:       { label: "Today's payments",      icon: "💵", type: "number",   page: "payments" },
    invoice_amount:       { label: "Invoice amount",        icon: "🧾", type: "currency", page: "invoices" },
    due_invoice:          { label: "Due amount (invoices)", icon: "📌", type: "currency", page: "invoices" },
    total_revenue:        { label: "Total revenue",         icon: "💹", type: "currency", page: "reports" },
    collection_total:     { label: "Collection total",      icon: "🏦", type: "currency", page: "collections" },
    recurring_invoices:   { label: "Recurring invoices",    icon: "🔁", type: "number",   page: "invoices" },
    monthly_overview:     { label: "Monthly overview",      icon: "📈", type: "currency", page: "dashboard" },
    revenue_pct:          { label: "Revenue collected",     icon: "📉", type: "percent",  page: "dashboard" },
  };

  // ─── BUILD FULL CONTEXT ────────────────────────────────────────────────────
  function buildContext() {
    scrapeAll();
    const ctx = {
      user: {},
      scraped: { ...scraped },
      currentPage: window.location.pathname,
      timestamp: new Date().toISOString(),
    };
    const d = getLoginData();
    if (d) {
      ctx.user = {
        name: d.name || d.userName || "User",
        email: d.email || "",
        companyId: d.company_id || d.companyId || null,
        role: d.role || d.userRole || null,
        apiUrl: d.apiUrl || d.api_url || null,
      };
    }
    window.billerqContext = ctx;
    return ctx;
  }

  // ─── INTENT DETECTION ─────────────────────────────────────────────────────
  const SEARCH_TRIGGERS = [
    "find customer", "search customer", "look up", "lookup", "find subscriber",
    "search for", "who is", "details of", "customer details", "show customer",
    "check customer", "search subscriber", "find for",
  ];

  function detectIntent(msg) {
    const m = msg.toLowerCase().trim();

    // Phone number
    if (/\b\d{10,12}\b/.test(msg)) return "search_customer";
    // Subscriber ID (e.g. SUB123)
    if (/\b[A-Za-z]{2,4}[-_]?\d{3,8}\b/.test(msg)) return "search_customer";
    // Search triggers
    for (const t of SEARCH_TRIGGERS) if (m.includes(t)) return "search_customer";

    // Metric queries
    for (const phrase of Object.keys(METRIC_ALIASES)) if (m.includes(phrase)) return "metric";

    // Dashboard summary
    if (["summary", "overview", "all stats", "dashboard", "how's business", "everything"].some(k => m.includes(k))) {
      // But not "go to dashboard" (that's navigation)
      if (!m.includes("go to") && !m.includes("open") && !m.includes("navigate")) return "summary";
    }

    // Navigation triggers
    const navTriggers = ["open ", "go to ", "take me to", "show page", "navigate to", "redirect to"];
    for (const t of navTriggers) if (m.includes(t)) return "navigate";
    // Direct page name
    for (const alias of Object.keys(NAV_ALIASES)) {
      if (m === alias || m === `open ${alias}` || m === `go to ${alias}` || m === `show ${alias}`) return "navigate";
    }

    // Workflow guidance
    for (const [topic, triggers] of Object.entries(WORKFLOW_TRIGGERS)) {
      for (const t of triggers) if (m.includes(t)) return "workflow:" + topic;
    }

    // Analysis
    const analysisTriggers = ["why", "reason", "trend", "dropping", "increasing", "decreasing",
      "compare", "insight", "pattern", "predict", "forecast", "growth", "decline", "analyse", "analyze"];
    for (const t of analysisTriggers) if (m.includes(t)) return "analysis";

    return "general";
  }

  // ─── RESPONSE BUILDERS ────────────────────────────────────────────────────

  function buildMetricCard(key) {
    const val = scraped[key];
    if (val === undefined || val === null) return null;
    const meta = METRIC_META[key];
    if (!meta) return null;
    const display = meta.type === "currency" ? fmt(val, "currency")
                  : meta.type === "percent"  ? pct(val)
                  : fmt(val, "number");
    return `${meta.icon} **${meta.label}:** ${display}`;
  }

  function buildSingleMetricResponse(metricKey) {
    // Show the asked metric PLUS all related metrics from same section
    const meta = METRIC_META[metricKey];
    if (!meta) return null;

    const val = scraped[metricKey];
    if (val === undefined || val === null) return null;

    // Primary answer
    const primary = buildMetricCard(metricKey);

    // Find related metrics (same page group)
    const related = Object.entries(METRIC_META)
      .filter(([k, m]) => k !== metricKey && m.page === meta.page && scraped[k] !== undefined)
      .map(([k]) => buildMetricCard(k))
      .filter(Boolean);

    let text = primary;
    if (related.length > 0) {
      text += `\n\n**Related on this page:**\n` + related.join("\n");
    }
    text += `\n\n📌 Data read live from your current screen.`;

    return {
      text,
      navigation: { label: `View ${meta.label} →`, url: PAGE_MAP[meta.page] || "/dashboard/default" },
      source: "dom",
    };
  }

  function buildDashboardSummary() {
    const rows = [];

    // Customer block
    if (scraped.active_customers !== undefined)   rows.push(buildMetricCard("active_customers"));
    if (scraped.inactive_customers !== undefined) rows.push(buildMetricCard("inactive_customers"));
    if (scraped.total_customers !== undefined)    rows.push(buildMetricCard("total_customers"));

    // Finance block
    if (scraped.invoice_amount !== undefined)    rows.push(buildMetricCard("invoice_amount"));
    if (scraped.due_invoice !== undefined)       rows.push(buildMetricCard("due_invoice"));
    if (scraped.monthly_collection !== undefined)rows.push(buildMetricCard("monthly_collection"));
    if (scraped.today_collection !== undefined)  rows.push(buildMetricCard("today_collection"));
    if (scraped.monthly_overview !== undefined)  rows.push(buildMetricCard("monthly_overview"));
    if (scraped.revenue_pct !== undefined)       rows.push(`📉 **Revenue collected:** ${pct(scraped.revenue_pct)}`);

    // Operations block
    if (scraped.open_complaints !== undefined)   rows.push(buildMetricCard("open_complaints"));
    if (scraped.active_subscriptions !== undefined) rows.push(buildMetricCard("active_subscriptions"));
    if (scraped.recurring_invoices !== undefined) rows.push(buildMetricCard("recurring_invoices"));

    // Connections
    if (scraped.iptv_connections !== undefined)  rows.push(`📡 **IPTV connections:** ${scraped.iptv_connections}`);
    if (scraped.ott_connections !== undefined)   rows.push(`📡 **OTT connections:** ${scraped.ott_connections}`);

    if (rows.length === 0) {
      return null; // Nothing scraped yet
    }

    return {
      text: `📊 **Dashboard Summary — Live Data**\n\n${rows.join("\n")}\n\n📌 All data read directly from your screen — no API call needed.`,
      navigation: { label: "View Full Dashboard →", url: "/dashboard/default" },
      source: "dom",
    };
  }

  function buildWorkflowResponse(topic) {
    const sop = WORKFLOW_SOPS[topic];
    if (!sop) return null;
    const steps = sop.steps.map((s, i) => `${i + 1}. ${s}`).join("\n");
    return {
      text: `📋 **${sop.title}**\n\n${steps}`,
      navigation: { label: `Open ${sop.title.split(" ")[0]} Page →`, url: PAGE_MAP[sop.page] || "/" },
      source: "knowledge_base",
    };
  }

  function buildNavigationResponse(msg) {
    const m = msg.toLowerCase().trim();

    // Check specific compound pages first
    const sorted = Object.entries(NAV_ALIASES).sort((a, b) => b[0].length - a[0].length);
    for (const [alias, pageKey] of sorted) {
      if (m.includes(alias)) {
        const url = PAGE_MAP[pageKey] || "/";
        const name = alias.replace(/\b\w/g, c => c.toUpperCase());

        // Gather data about the target page from scraped
        let extraData = "";
        if (pageKey === "customers" && scraped.active_customers !== undefined) {
          extraData = `\n\n📊 **Current data:**\n${buildMetricCard("active_customers") || ""}`;
          if (scraped.total_customers !== undefined) extraData += `\n${buildMetricCard("total_customers")}`;
        }
        if ((pageKey === "complaints") && scraped.open_complaints !== undefined) {
          extraData = `\n\n📊 **Current data:**\n${buildMetricCard("open_complaints")}`;
        }
        if ((pageKey === "collections" || pageKey === "payments") && scraped.monthly_collection !== undefined) {
          extraData = `\n\n📊 **Current data:**\n${buildMetricCard("monthly_collection") || ""}`;
        }

        return {
          text: `Opening **${name}** page.${extraData}`,
          navigation: { label: `Go to ${name} →`, url },
          source: "local",
        };
      }
    }
    return null;
  }

  // ─── MAIN LOCAL HANDLER ───────────────────────────────────────────────────
  function handleLocally(message) {
    const intent = detectIntent(message);
    const m = message.toLowerCase();

    // 1. Summary — all data first
    if (intent === "summary") {
      const summary = buildDashboardSummary();
      if (summary) return summary;
      // No data yet → send to backend
      return null;
    }

    // 2. Single metric
    if (intent === "metric") {
      for (const [phrase, metricKey] of Object.entries(METRIC_ALIASES)) {
        if (m.includes(phrase)) {
          const resp = buildSingleMetricResponse(metricKey);
          if (resp) return resp;
          break;
        }
      }
      // Metric asked but not in DOM → backend
      return null;
    }

    // 3. Navigation — show data then link
    if (intent === "navigate") {
      const nav = buildNavigationResponse(message);
      if (nav) return nav;
      return {
        text: "Which page would you like? Try:\n**Customers · Payments · Invoices · Subscriptions · Complaints · Reports · Settings · Dashboard**",
        navigation: null,
        source: "local",
      };
    }

    // 4. Workflow SOPs
    if (intent.startsWith("workflow:")) {
      const topic = intent.split(":")[1];
      const resp = buildWorkflowResponse(topic);
      if (resp) return resp;
    }

    // 5. Everything else → backend
    return null;
  }

  // ─── STATE ────────────────────────────────────────────────────────────────
  const state = {
    isOpen: false,
    isLoading: false,
    messages: [],
    sessionId: "bq_" + Math.random().toString(36).substr(2, 9) + "_" + Date.now(),
  };

  // ─── STYLES ──────────────────────────────────────────────────────────────
  function injectStyles() {
    if (document.getElementById("bq-style")) return;
    const s = document.createElement("style");
    s.id = "bq-style";
    s.textContent = `
    #billerq-copilot-root *{box-sizing:border-box;font-family:'Rubik','Roboto',-apple-system,sans-serif;}
    #bq-fab{position:fixed;bottom:28px;right:28px;width:56px;height:56px;border-radius:50%;
      background:linear-gradient(135deg,#534686,#7c6bb5);border:none;cursor:pointer;
      box-shadow:0 4px 20px rgba(83,70,134,.45);z-index:99998;display:flex;align-items:center;
      justify-content:center;transition:transform .2s,box-shadow .2s;outline:none;}
    #bq-fab:hover{transform:scale(1.08);box-shadow:0 6px 28px rgba(83,70,134,.55);}
    #bq-fab:active{transform:scale(.96);}
    #bq-fab svg{width:26px;height:26px;fill:#fff;transition:opacity .2s;}
    #bq-fab .bq-close-icon{display:none;}
    #bq-fab.open .bq-chat-icon{display:none;}
    #bq-fab.open .bq-close-icon{display:block;}
    #bq-badge{position:absolute;top:-3px;right:-3px;background:#ff4757;color:#fff;
      border-radius:50%;width:18px;height:18px;font-size:10px;font-weight:700;
      display:none;align-items:center;justify-content:center;border:2px solid #fff;}
    #bq-panel{position:fixed;bottom:96px;right:28px;width:390px;height:560px;
      background:#fff;border-radius:20px;box-shadow:0 12px 48px rgba(0,0,0,.18);
      z-index:99997;display:flex;flex-direction:column;overflow:hidden;
      opacity:0;transform:translateY(20px) scale(.97);transition:opacity .25s,transform .25s;
      pointer-events:none;}
    #bq-panel.open{opacity:1;transform:translateY(0) scale(1);pointer-events:all;}
    #bq-header{background:linear-gradient(135deg,#534686,#7c6bb5);padding:14px 16px;
      display:flex;align-items:center;gap:10px;flex-shrink:0;}
    #bq-avatar{width:38px;height:38px;border-radius:50%;background:rgba(255,255,255,.2);
      display:flex;align-items:center;justify-content:center;flex-shrink:0;
      font-size:15px;font-weight:700;color:#fff;border:2px solid rgba(255,255,255,.3);}
    #bq-header-text{flex:1;min-width:0;}
    #bq-header-title{color:#fff;font-size:14px;font-weight:600;margin:0;line-height:1.2;}
    #bq-header-sub{color:rgba(255,255,255,.75);font-size:11px;margin:2px 0 0;
      display:flex;align-items:center;gap:4px;}
    #bq-header-sub::before{content:'';display:inline-block;width:6px;height:6px;
      border-radius:50%;background:#4ade80;flex-shrink:0;}
    #bq-clear-btn{background:rgba(255,255,255,.15);border:none;color:#fff;border-radius:8px;
      padding:5px 10px;font-size:11px;cursor:pointer;transition:background .2s;font-family:inherit;}
    #bq-clear-btn:hover{background:rgba(255,255,255,.25);}
    #bq-messages{flex:1;overflow-y:auto;padding:14px 12px;display:flex;
      flex-direction:column;gap:10px;background:#f7f6fb;scroll-behavior:smooth;}
    #bq-messages::-webkit-scrollbar{width:4px;}
    #bq-messages::-webkit-scrollbar-thumb{background:#d0cbe8;border-radius:4px;}
    .bq-msg{display:flex;gap:8px;max-width:94%;animation:bqIn .2s ease;}
    @keyframes bqIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
    .bq-msg.user{align-self:flex-end;flex-direction:row-reverse;}
    .bq-msg.bot{align-self:flex-start;}
    .bq-av{width:28px;height:28px;border-radius:50%;background:linear-gradient(135deg,#534686,#7c6bb5);
      display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;
      color:#fff;flex-shrink:0;margin-top:2px;}
    .bq-msg.user .bq-av{display:none;}
    .bq-bubble{padding:10px 14px;border-radius:16px;font-size:13.5px;line-height:1.6;
      word-break:break-word;}
    .bq-bubble strong{font-weight:600;}
    .bq-msg.user .bq-bubble{background:linear-gradient(135deg,#534686,#7c6bb5);
      color:#fff;border-bottom-right-radius:4px;}
    .bq-msg.bot .bq-bubble{background:#fff;color:#2d2d2d;border-bottom-left-radius:4px;
      box-shadow:0 1px 4px rgba(0,0,0,.08);}
    .bq-src{font-size:10px;color:#aaa;margin-top:4px;display:block;}
    .bq-navlink{display:inline-block;margin-top:10px;padding:7px 16px;
      background:#f0edf9;color:#534686;border-radius:20px;font-size:12.5px;
      font-weight:600;text-decoration:none;cursor:pointer;border:1.5px solid #d5cff0;
      transition:background .15s,transform .1s;}
    .bq-navlink:hover{background:#e4dff5;transform:translateY(-1px);}
    .bq-customer-card{background:#f0edf9;border:1px solid #d5cff0;border-radius:10px;
      padding:8px 12px;margin-top:6px;font-size:12.5px;}
    .bq-card-name{font-weight:600;color:#534686;}
    .bq-card-detail{color:#666;margin-top:2px;}
    .bq-badge{display:inline-block;font-size:10px;padding:1px 7px;border-radius:10px;font-weight:600;margin-left:6px;}
    .bq-active{background:#dcfce7;color:#16a34a;}
    .bq-inactive{background:#fee2e2;color:#dc2626;}
    #bq-typing{display:none;align-self:flex-start;padding:10px 14px;background:#fff;
      border-radius:16px;border-bottom-left-radius:4px;box-shadow:0 1px 4px rgba(0,0,0,.08);}
    #bq-typing.show{display:flex;gap:4px;align-items:center;}
    .bq-dot{width:7px;height:7px;border-radius:50%;background:#b0a8d4;animation:bqBounce 1.2s infinite;}
    .bq-dot:nth-child(2){animation-delay:.2s;}.bq-dot:nth-child(3){animation-delay:.4s;}
    @keyframes bqBounce{0%,60%,100%{transform:translateY(0)}30%{transform:translateY(-6px)}}
    #bq-welcome{display:flex;flex-direction:column;align-items:center;justify-content:center;
      text-align:center;padding:20px 16px;gap:6px;flex:1;}
    #bq-welcome-icon{width:52px;height:52px;border-radius:50%;
      background:linear-gradient(135deg,#534686,#7c6bb5);display:flex;align-items:center;
      justify-content:center;margin-bottom:4px;box-shadow:0 4px 16px rgba(83,70,134,.3);}
    #bq-welcome-icon svg{width:26px;height:26px;fill:#fff;}
    #bq-welcome h3{font-size:16px;font-weight:700;color:#2d2d2d;margin:0;}
    #bq-welcome p{font-size:12.5px;color:#888;margin:0;line-height:1.5;}
    #bq-welcome .bq-hint{font-size:11px;color:#aaa;margin-top:4px;background:#f0edf9;
      padding:6px 12px;border-radius:12px;border:1px solid #e0daf0;}
    #bq-chips{padding:0 12px 10px;display:flex;flex-wrap:wrap;gap:6px;background:#f7f6fb;}
    .bq-chip{background:#fff;border:1.5px solid #e0daf0;color:#534686;border-radius:20px;
      padding:5px 12px;font-size:11.5px;font-weight:500;cursor:pointer;transition:all .15s;
      font-family:inherit;}
    .bq-chip:hover{background:#534686;color:#fff;border-color:#534686;}
    #bq-input-area{display:flex;align-items:flex-end;gap:8px;padding:10px 14px;
      background:#fff;border-top:1px solid #ede9f7;flex-shrink:0;}
    #bq-input{flex:1;border:1.5px solid #e0daf0;border-radius:22px;padding:10px 16px;
      font-size:13px;font-family:inherit;resize:none;outline:none;max-height:100px;min-height:40px;
      line-height:1.4;color:#2d2d2d;transition:border-color .2s;overflow-y:auto;}
    #bq-input:focus{border-color:#534686;}
    #bq-input::placeholder{color:#bbb;}
    #bq-send{width:40px;height:40px;border-radius:50%;
      background:linear-gradient(135deg,#534686,#7c6bb5);border:none;cursor:pointer;
      display:flex;align-items:center;justify-content:center;flex-shrink:0;
      transition:transform .15s,opacity .15s;}
    #bq-send:hover{transform:scale(1.08);}
    #bq-send:disabled{opacity:.5;cursor:not-allowed;transform:none;}
    #bq-send svg{width:18px;height:18px;fill:#fff;}
    .bq-ts{font-size:10px;color:#bbb;text-align:center;margin:4px 0;width:100%;}
    @media(max-width:480px){
      #bq-panel{width:calc(100vw - 16px);right:8px;bottom:80px;height:70vh;border-radius:14px;}
      #bq-fab{bottom:18px;right:18px;width:50px;height:50px;}
    }
    `;
    document.head.appendChild(s);
  }

  // ─── BUILD HTML ───────────────────────────────────────────────────────────
  function buildWidget() {
    const role = getUserRole();
    const roleLabel = role ? (role[0].toUpperCase() + role.slice(1).toLowerCase() + " · ") : "";

    const root = document.createElement("div");
    root.id = WIDGET_ID;
    root.innerHTML = `
    <button id="bq-fab" aria-label="BillerQ AI Copilot">
      <svg class="bq-chat-icon" viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-2 10H6v-2h12v2zm0-3H6V7h12v2z"/></svg>
      <svg class="bq-close-icon" viewBox="0 0 24 24"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
      <span id="bq-badge"></span>
    </button>
    <div id="bq-panel" role="dialog">
      <div id="bq-header">
        <div id="bq-avatar">BQ</div>
        <div id="bq-header-text">
          <p id="bq-header-title">BillerQ Copilot</p>
          <p id="bq-header-sub">${roleLabel}Online</p>
        </div>
        <button id="bq-clear-btn">Clear</button>
      </div>
      <div id="bq-messages">
        <div id="bq-welcome">
          <div id="bq-welcome-icon"><svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 14.5v-9l6 4.5-6 4.5z"/></svg></div>
          <h3>Hi, <span id="bq-uname">${getUserName()}</span> 👋</h3>
          <p>Ask me anything about your BillerQ data — I read it live from your screen.</p>
          <p class="bq-hint">💡 "Active customers" · "Dashboard summary" · "Find customer John"</p>
        </div>
        <div id="bq-typing"><div class="bq-dot"></div><div class="bq-dot"></div><div class="bq-dot"></div></div>
      </div>
      <div id="bq-chips">
        <button class="bq-chip">Dashboard summary</button>
        <button class="bq-chip">Active customers</button>
        <button class="bq-chip">Today's collection</button>
        <button class="bq-chip">Open complaints</button>
        <button class="bq-chip">Go to payments</button>
        <button class="bq-chip">How to add invoice</button>
      </div>
      <div id="bq-input-area">
        <textarea id="bq-input" placeholder="Ask anything — customers, payments, reports…" rows="1" aria-label="Chat message"></textarea>
        <button id="bq-send" disabled><svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg></button>
      </div>
    </div>`;
    document.body.appendChild(root);
  }

  // ─── RENDER ───────────────────────────────────────────────────────────────
  function esc(t) {
    const d = document.createElement("div");
    d.appendChild(document.createTextNode(String(t)));
    return d.innerHTML;
  }

  function md(text) {
    return esc(text)
      .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
      .replace(/\n/g, "<br/>");
  }

  function renderMessages() {
    const container = document.getElementById("bq-messages");
    const welcome   = document.getElementById("bq-welcome");
    const typing    = document.getElementById("bq-typing");
    if (!container) return;

    // Remove old messages (keep welcome + typing)
    Array.from(container.children).forEach(ch => {
      if (ch.id !== "bq-welcome" && ch.id !== "bq-typing") container.removeChild(ch);
    });

    welcome.style.display = state.messages.length > 0 ? "none" : "flex";

    state.messages.forEach((msg, idx) => {
      if (idx % 10 === 0) {
        const ts = document.createElement("div");
        ts.className = "bq-ts";
        ts.textContent = new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
        container.insertBefore(ts, typing);
      }

      const el = document.createElement("div");
      el.className = "bq-msg " + msg.role;

      const sourceIcon = {
        "dom": "⚡ Live from screen",
        "local": "⚡ Instant",
        "knowledge_base": "📖 Guide",
        "database": "💾 Database",
        "api": "🌐 API",
        "ai": "🤖 AI",
      };

      let html = `<div class="bq-av">BQ</div><div class="bq-bubble">`;
      html += md(msg.text);

      // Source label
      if (msg.source && msg.role === "bot") {
        html += `<span class="bq-src">${sourceIcon[msg.source] || "🤖 AI"}</span>`;
      }

      // Navigation link — ALWAYS LAST
      if (msg.navigation && msg.navigation.url) {
        html += `<br/><a class="bq-navlink" href="${esc(msg.navigation.url)}" target="_blank">${esc(msg.navigation.label)}</a>`;
      }

      // Customer result cards
      if (msg.customerResults && msg.customerResults.length > 0) {
        msg.customerResults.slice(0, 5).forEach(c => {
          const name   = esc(c.name || c.full_name || "Unknown");
          const phone  = esc(c.phone || c.mobile || "—");
          const area   = esc(c.area || "—");
          const subId  = esc(c.subscriber_id || "—");
          const status = c.status || "unknown";
          const bc     = status === "active" ? "bq-active" : "bq-inactive";
          html += `<div class="bq-customer-card">
            <div class="bq-card-name">${status === "active" ? "✅" : "🔴"} ${name}<span class="bq-badge ${bc}">${status}</span></div>
            <div class="bq-card-detail">🪪 ${subId} · 📱 ${phone} · 📍 ${area}</div>
          </div>`;
        });
      }

      html += `</div>`;
      el.innerHTML = html;
      container.insertBefore(el, typing);
    });

    typing.classList.toggle("show", state.isLoading);
    container.scrollTop = container.scrollHeight;
  }

  // ─── SEND ─────────────────────────────────────────────────────────────────
  async function send(text) {
    if (!text.trim() || state.isLoading) return;

    // Hide chips after first message
    const chips = document.getElementById("bq-chips");
    if (chips) chips.style.display = "none";

    state.messages.push({ role: "user", text: text.trim() });
    state.isLoading = true;
    renderMessages();

    const input = document.getElementById("bq-input");
    if (input) { input.value = ""; input.style.height = "40px"; }
    const sendBtn = document.getElementById("bq-send");
    if (sendBtn) sendBtn.disabled = true;

    try {
      // ── Step 1: Re-scrape DOM first ──────────────────────────────────────
      scrapeAll();

      // ── Step 2: Try local handling ────────────────────────────────────────
      const localResp = handleLocally(text);
      if (localResp) {
        state.messages.push({
          role: "bot",
          text: localResp.text,
          navigation: localResp.navigation || null,
          source: localResp.source || "local",
        });
        state.isLoading = false;
        renderMessages();
        return;
      }

      // ── Step 3: Send to backend ────────────────────────────────────────────
      const token     = getUserToken();
      const companyId = getCompanyId();
      const ctx       = buildContext();

      const headers = { "Content-Type": "application/json" };
      if (token)     headers["Authorization"]  = "Bearer " + token;
      if (companyId) headers["X-Company-Id"]   = String(companyId);

      const resp = await fetch(API_BASE + "/chat", {
        method: "POST",
        headers,
        body: JSON.stringify({
          message: text.trim(),
          session_id: state.sessionId,
          company_id: companyId,
          context: {
            ...ctx,
            scraped_data: scraped,     // Full DOM data sent to model
            current_page: window.location.pathname,
          },
        }),
      });

      if (!resp.ok) throw new Error("HTTP " + resp.status);

      const data = await resp.json();
      let customerResults = [];
      if (data.intent === "customer_search" && data.data && data.data.results) {
        customerResults = data.data.results;
      }

      state.messages.push({
        role: "bot",
        text: data.message || "I couldn't process that. Please try again.",
        navigation: data.navigation || null,
        source: data.source || "ai",
        customerResults,
      });

    } catch (err) {
      console.error("[BillerQ Copilot]", err);
      // Retry local with more context
      const fallback = buildDashboardSummary();
      state.messages.push({
        role: "bot",
        text: fallback
          ? `Backend offline, but here's what I can see:\n\n${fallback.text.replace("📊 **Dashboard Summary — Live Data**\n\n", "")}`
          : "Backend is offline. Navigation still works — try: **'Open customers'** or **'Go to complaints'**",
        navigation: { label: "Go to Dashboard →", url: "/dashboard/default" },
        source: "dom",
      });
    } finally {
      state.isLoading = false;
      renderMessages();
    }
  }

  // ─── PANEL CONTROLS ───────────────────────────────────────────────────────
  function openPanel() {
    state.isOpen = true;
    document.getElementById("bq-panel").classList.add("open");
    document.getElementById("bq-fab").classList.add("open");
    const badge = document.getElementById("bq-badge");
    if (badge) badge.style.display = "none";
    scrapeAll(); // Fresh scrape on open
    renderMessages();
    setTimeout(() => { const i = document.getElementById("bq-input"); if (i) i.focus(); }, 300);
  }

  function closePanel() {
    state.isOpen = false;
    document.getElementById("bq-panel").classList.remove("open");
    document.getElementById("bq-fab").classList.remove("open");
  }

  function togglePanel() { state.isOpen ? closePanel() : openPanel(); }

  function clearConversation() {
    state.messages = [];
    state.sessionId = "bq_" + Math.random().toString(36).substr(2, 9) + "_" + Date.now();
    const chips = document.getElementById("bq-chips");
    if (chips) chips.style.display = "flex";
    renderMessages();
    fetch(API_BASE + "/session/" + state.sessionId, { method: "DELETE" }).catch(() => {});
  }

  // ─── EVENTS ───────────────────────────────────────────────────────────────
  function bindEvents() {
    document.getElementById("bq-fab").addEventListener("click", togglePanel);
    document.getElementById("bq-clear-btn").addEventListener("click", clearConversation);
    document.getElementById("bq-send").addEventListener("click", () => {
      send(document.getElementById("bq-input").value);
    });

    const input = document.getElementById("bq-input");
    input.addEventListener("keydown", e => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input.value); }
    });
    input.addEventListener("input", () => {
      document.getElementById("bq-send").disabled = !input.value.trim();
      input.style.height = "40px";
      input.style.height = Math.min(input.scrollHeight, 100) + "px";
    });

    document.querySelectorAll(".bq-chip").forEach(btn => {
      btn.addEventListener("click", () => send(btn.textContent.trim()));
    });

    document.addEventListener("keydown", e => { if (e.key === "Escape" && state.isOpen) closePanel(); });
    document.addEventListener("click", e => {
      const panel = document.getElementById("bq-panel");
      const fab   = document.getElementById("bq-fab");
      if (state.isOpen && panel && fab && !panel.contains(e.target) && !fab.contains(e.target)) closePanel();
    });
  }

  // ─── MOUNT ────────────────────────────────────────────────────────────────
  function mountWidget() {
    if (document.getElementById(WIDGET_ID)) return;
    injectStyles();
    buildWidget();
    bindEvents();
    // Initial scrape
    scrapeAll();
    // Periodic re-scrape as React updates DOM
    setInterval(scrapeAll, SCRAPE_INTERVAL);
    console.log("[BillerQ Copilot v5.0] Mounted. Scraped:", scraped);
  }

  // ─── INIT ─────────────────────────────────────────────────────────────────
  function isAuthPage() {
    const p = window.location.pathname;
    return p === "/" || ["signin","signup","login","forget","reset","otp","phoneOtp"]
      .some(k => p.includes(k));
  }

  function observeRouteChange() {
    let lastPath = window.location.pathname;
    setInterval(() => {
      if (window.location.pathname !== lastPath) {
        lastPath = window.location.pathname;
        if (!document.getElementById(WIDGET_ID) && !isAuthPage() && isLoggedIn()) {
          loadCryptoJS();
          setTimeout(mountWidget, MOUNT_DELAY_MS);
        }
        // Re-scrape on page change
        if (document.getElementById(WIDGET_ID)) setTimeout(scrapeAll, 1500);
      }
    }, 500);
  }

  function init() {
    if (isAuthPage()) { observeRouteChange(); return; }
    if (!isLoggedIn()) { observeRouteChange(); return; }
    loadCryptoJS();
    observeRouteChange(); // Still watch for SPA navigation
    setTimeout(mountWidget, MOUNT_DELAY_MS);
  }

  // ─── BOOTSTRAP ────────────────────────────────────────────────────────────
  if (document.readyState === "complete") {
    setTimeout(init, 500);
  } else {
    window.addEventListener("load", () => setTimeout(init, 500));
  }

})();