// TODO: Port upload from frontend/js/upload.js
// Features to build:
//   - Drag-and-drop file zone
//   - Support: CSV, XLSX, PDF
//   - Upload progress indicator
//   - Duplicate file detection (409 error handling)
//   - Upload history table
//   - Delete uploaded file

export default function Upload() {
  return (
    <div className="page">
      <div className="page-header">
        <h1>Upload Data</h1>
        <p>CSV, Excel, PDF — coming soon</p>
      </div>
      <div className="placeholder-card" style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        📁 Drop files here
      </div>
    </div>
  )
}
