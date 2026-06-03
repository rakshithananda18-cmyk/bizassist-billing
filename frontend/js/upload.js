/* =========================================
   upload.js
   Handles: file upload via event delegation
   (survives innerHTML swaps), delete upload,
   render uploads list widget.
   Depends on: config.js
========================================= */


/* -----------------------------------------
   UPLOAD — event delegation on document
   so the listener survives innerHTML swaps
   in selectSidebar / openDatabasePanel.
----------------------------------------- */

document.addEventListener("change", async function (e) {

    /* Handle #file-upload, #file-upload-dash, #file-upload-db, and #file-upload-chat inputs */
    if (!e.target || (e.target.id !== "file-upload" && e.target.id !== "file-upload-dash" && e.target.id !== "file-upload-db" && e.target.id !== "file-upload-chat")) return;

    if (DEBUG) console.log("File upload input changed:", e.target.id);

    const file = e.target.files[0];
    if (!file) return;

    const triggerButton = findTriggerButtonForInput(e.target);
    await handleFileUpload(file, triggerButton);
});

/* Find the button element that triggered the file input dialog */
function findTriggerButtonForInput(input) {
    if (!input || !input.id) return null;
    const selector = `button[onclick*="${input.id}"]`;
    const buttons = document.querySelectorAll(selector);
    for (let btn of buttons) {
        if (btn.offsetWidth > 0 || btn.offsetHeight > 0) {
            return btn;
        }
    }
    return buttons[0] || null;
}

/* Centralized handler for file upload */
async function handleFileUpload(file, triggerButton) {
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);

    // Apply loading state to trigger button
    if (typeof setElementLoading === "function" && triggerButton) {
        setElementLoading(triggerButton, true, "Uploading...");
    }

    try {
        if (DEBUG) console.log("Uploading file...");

        const response = await fetch(`${API_BASE}/upload`, {
            method : "POST",
            body   : formData
        });

        const data = await response.json();

        if (!response.ok || data.error) {
            throw new Error(data.error || `Upload failed (${response.status})`);
        }

        if (DEBUG) console.log("Upload response:", data);

        await showCustomAlert(
`File type: ${data.file_type}
Rows processed: ${data.rows}`,
            "File Uploaded Successfully"
        );

        // Clear all file inputs
        const fileInputs = document.querySelectorAll('input[type="file"]');
        fileInputs.forEach(input => { input.value = ""; });

        // Refresh all views
        try { await loadUploads();          } catch (err) { if (DEBUG) console.error(err); }
        try { await loadDashboardSummary(); } catch (err) { if (DEBUG) console.error(err); }
        try { await loadTopCustomers();     } catch (err) { if (DEBUG) console.error(err); }

        // Refresh currently active sidebar view
        const activeView = document.documentElement.getAttribute("data-active") || "dashboard";
        if (activeView === "database") {
            try { await openDatabasePanel(); } catch (err) { if (DEBUG) console.error(err); }
        } else if (typeof selectSidebar === "function") {
            selectSidebar(activeView);
        }

    } catch (error) {
        if (DEBUG) console.error(error);
        await showCustomAlert("Upload failed: " + error.message, "Upload Failed");
    } finally {
        // Clear loading state
        if (typeof setElementLoading === "function" && triggerButton) {
            setElementLoading(triggerButton, false);
        }
    }
}


/* -----------------------------------------
   DELETE UPLOAD
----------------------------------------- */

async function deleteUpload(fileId) {

    const confirmed = await showCustomConfirm(
        "Are you sure you want to delete this file? This action cannot be undone.",
        "Delete File"
    );

    if (!confirmed) return;

    try {

        const response = await fetch(`${API_BASE}/upload/${fileId}`, {
            method: "DELETE"
        });

        const data = await response.json();

        /* Backend returns HTTP 200 with {error} for not-found.
           Check both the status AND the body. */
        if (!response.ok || data.error) {
            throw new Error(data.error || `Delete failed (${response.status})`);
        }

        if (DEBUG) console.log("File deleted:", data);

        await showCustomAlert("File deleted successfully", "Delete Successful");

        /* Refresh each view independently */
        try { await loadUploads();          } catch (err) { if (DEBUG) console.error(err); }
        try { await loadDashboardSummary(); } catch (err) { if (DEBUG) console.error(err); }

        /* Only reload DB panel if that view is currently active */
        if (document.documentElement.getAttribute("data-active") === "database") {
            try { await openDatabasePanel(); } catch (err) { if (DEBUG) console.error(err); }
        }

    } catch (error) {

        if (DEBUG) console.error(error);
        await showCustomAlert("Failed to delete file: " + error.message, "Error");
    }
}


/* -----------------------------------------
   LOAD UPLOADS LIST  (dashboard widget)
----------------------------------------- */

async function loadUploads() {

    const uploadsList = document.getElementById("uploads-list");
    if (!uploadsList) return;

    try {

        const response = await fetch(`${API_BASE}/uploads`);

        if (!response.ok) throw new Error("Failed to load uploads");

        const data = await response.json();

        uploadsList.innerHTML = "";

        if (data.length === 0) {
            uploadsList.innerHTML = `
                <div class="empty-upload">No uploaded files yet</div>
            `;
            return;
        }

        data.forEach(file => {

            uploadsList.innerHTML += `
                <div class="upload-item">

                    <div class="upload-top">

                        <strong>${file.filename}</strong>

                        <span class="upload-badge">${file.type}</span>

                        <button
                            class="delete-btn"
                            onclick="deleteUpload(${file.id})"
                            title="Delete file"
                        >
                            ✕
                        </button>

                    </div>

                    <div class="upload-meta">
                        ${file.rows} rows • ${file.uploaded}
                    </div>

                </div>
            `;
        });

    } catch (error) {

        if (DEBUG) console.error(error);

        uploadsList.innerHTML = `
            <div class="upload-error">Failed to load uploads</div>
        `;
    }
}


/* -----------------------------------------
   TEST UPLOAD  (Dev Testing widget)
----------------------------------------- */

async function testUpload() {

    const fileInput = document.getElementById("file-upload");
    const file      = fileInput ? fileInput.files[0] : null;

    if (!file) {
        await showCustomAlert("Please select a file first", "Notice");
        return;
    }

    const formData = new FormData();
    formData.append("file", file);

    if (DEBUG) console.log("Testing file upload with:", formData);

    try {

        const response = await fetch(`${API_BASE}/upload`, {
            method : "POST",
            body   : formData
        });

        const data = await response.json();

        if (DEBUG) console.log(data);

        await showCustomAlert(`Upload Success\nRows: ${data.rows}`, "Dev Testing");

        loadUploads();

    } catch (error) {

        console.error(error);
        await showCustomAlert("Upload Failed", "Error");
    }
}


if (localStorage.getItem("user")) {
    loadUploads();
}
