// Dynamics 365 Business Central - Document Intake Portal
// Frontend UI/UX with Mock Document Extraction & Form Mapping

const { useState, useEffect, useRef, useMemo } = React;

// Category Constants
const CATEGORIES = {
  GST: "GST/ABN/TRN Registration Certificate",
  PAN: "PAN Card (Company/Individual)",
  CONTRACT: "Customer Agreement / Contract / Purchase Order / Sale Order"
};

// Helper icon component wrapper using lucide
const Icon = ({ name, className = "w-4 h-4", ...props }) => {
  useEffect(() => {
    if (window.lucide) {
      window.lucide.createIcons();
    }
  }, [name, className]);

  return <i data-lucide={name} className={className} {...props}></i>;
};

function App() {
  // --- Blank Initial States ---
  const [files, setFiles] = useState([]);

  const [formData, setFormData] = useState({
    companyName: "",
    contactName: "",
    billingAddress: "",
    city: "",
    state: "",
    zipCode: "",
    country: "",
    emailTo: "",
    emailCc: [],
    phoneNumber: "",
    paymentTerms: "",
    salesperson: "",
    region: "",
    type: "" // Dropdown: Services / License
  });

  // Track auto-filled fields from OCR mock
  const [autoFilledFields, setAutoFilledFields] = useState({});
  const [validationErrors, setValidationErrors] = useState({});
  const [isDragging, setIsDragging] = useState(false);
  const [activePreviewFile, setActivePreviewFile] = useState(null);
  const [showSubmitModal, setShowSubmitModal] = useState(false);
  const [ccInputValue, setCcInputValue] = useState("");
  const [ccError, setCcError] = useState("");
  const [lastSaved, setLastSaved] = useState("Not saved yet");
  const [isSaving, setIsSaving] = useState(false);
  const [toasts, setToasts] = useState([]);
  const [isUploadPanelCollapsed, setIsUploadPanelCollapsed] = useState(false);

  const fileInputRef = useRef(null);

  // --- Toast Manager ---
  const addToast = (type, title, message) => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, type, title, message }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4500);
  };

  const removeToast = (id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  useEffect(() => {
    if (window.lucide) {
      window.lucide.createIcons();
    }
  }, [files, toasts, activePreviewFile, showSubmitModal, autoFilledFields, validationErrors]);

  // --- Validation ---
  const validateField = (name, value) => {
    let error = "";
    if (name === "companyName" && !value.trim()) {
      error = "Company Name is required";
    } else if (name === "contactName" && !value.trim()) {
      error = "Contact Name is required";
    } else if (name === "billingAddress" && !value.trim()) {
      error = "Billing Address is required";
    } else if (name === "city" && !value.trim()) {
      error = "City is required";
    } else if (name === "state" && !value.trim()) {
      error = "State is required";
    } else if (name === "zipCode" && !value.trim()) {
      error = "Zip code / Pin code is required";
    } else if (name === "country" && !value.trim()) {
      error = "Country is required";
    } else if (name === "emailTo") {
      if (!value.trim()) {
        error = "Email ID TO is required";
      } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) {
        error = "Invalid email format";
      }
    } else if (name === "phoneNumber") {
      if (!value.trim()) {
        error = "Phone Number is required";
      } else if (!/^[0-9\s\-\(\)\+]{7,16}$/.test(value)) {
        error = "Invalid phone format (min 7 digits)";
      }
    }

    setValidationErrors((prev) => ({ ...prev, [name]: error }));
    return !error;
  };

  const isFormValid = useMemo(() => {
    const requiredKeys = ["companyName", "contactName", "billingAddress", "city", "state", "zipCode", "country", "emailTo", "phoneNumber"];
    for (let key of requiredKeys) {
      if (!formData[key] || !formData[key].toString().trim()) return false;
      if (validationErrors[key]) return false;
    }
    const isExtracting = files.some((f) => f.status === "Extracting");
    return !isExtracting;
  }, [formData, validationErrors, files]);

  // --- Handlers ---
  const handleInputChange = (field, value) => {
    setFormData((prev) => ({ ...prev, [field]: value }));

    // Clear auto-filled badge on manual edit
    if (autoFilledFields[field]) {
      setAutoFilledFields((prev) => {
        const next = { ...prev };
        delete next[field];
        return next;
      });
      addToast("info", "Field Edited", `Manual edit override saved for ${field}`);
    }

    validateField(field, value);
  };

  const handleAddCcEmail = (e) => {
    if (e.key === "Enter" || e.key === "," || e.key === " ") {
      e.preventDefault();
      const val = ccInputValue.trim().replace(/,/g, "");
      if (!val) return;

      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(val)) {
        setCcError("Invalid email format for CC");
        return;
      }

      if (formData.emailCc.includes(val)) {
        setCcError("Email already added");
        return;
      }

      setFormData((prev) => ({
        ...prev,
        emailCc: [...prev.emailCc, val]
      }));
      setCcInputValue("");
      setCcError("");
    }
  };

  const handleRemoveCcEmail = (emailToRemove) => {
    setFormData((prev) => ({
      ...prev,
      emailCc: prev.emailCc.filter((e) => e !== emailToRemove)
    }));
  };

  // --- Mock OCR Extraction ---
  const simulateDocumentExtraction = (fileId, category, fileName) => {
    // [BACKEND INTEGRATION]: Extraction API Call
    setFiles((prev) =>
      prev.map((f) => (f.id === fileId ? { ...f, status: "Extracting" } : f))
    );

    setTimeout(() => {
      let extracted = {};

      if (category === CATEGORIES.GST) {
        extracted = {
          companyName: fileName.toLowerCase().includes("acme") ? "Acme Global Logistics Corp" : "Nexus Industrial Solutions Ltd",
          billingAddress: "1028 Enterprise Boulevard, Suite 500",
          city: "Chicago",
          state: "Illinois",
          zipCode: "60607",
          country: "United States",
          emailTo: "accounts.payable@nexus-solutions.com",
          phoneNumber: "+1 312-555-0144"
        };
      } else if (category === CATEGORIES.PAN) {
        extracted = {
          companyName: "Vanguard Tech Innovations",
          contactName: "Samantha Reed",
          city: "Austin",
          state: "Texas",
          zipCode: "78701",
          country: "United States"
        };
      } else if (category === CATEGORIES.CONTRACT) {
        extracted = {
          companyName: "Horizon Energy Partners LLC",
          contactName: "Marcus Vance",
          paymentTerms: "Net 30",
          salesperson: "Alex Morgan",
          region: "North America",
          type: "Services"
        };
      }

      const newlyAutoFilled = {};
      setFormData((prev) => {
        const next = { ...prev };
        Object.keys(extracted).forEach((key) => {
          next[key] = extracted[key];
          newlyAutoFilled[key] = true;
        });
        return next;
      });

      setAutoFilledFields((prev) => ({
        ...prev,
        ...newlyAutoFilled
      }));

      setFiles((prev) =>
        prev.map((f) =>
          f.id === fileId
            ? { ...f, status: "Mapped", extractedData: extracted }
            : f
        )
      );

      const count = Object.keys(extracted).length;
      addToast(
        "success",
        "✨ Data Extracted & Auto-Filled",
        `Extracted ${count} fields from "${fileName}"`
      );
    }, 1400);
  };

  const handleReExtractField = (fieldName) => {
    addToast("info", "Re-extracting Field", `Re-verifying ${fieldName} from document...`);
    setTimeout(() => {
      setAutoFilledFields((prev) => ({ ...prev, [fieldName]: true }));
      addToast("success", "Field Re-extracted", `${fieldName} updated.`);
    }, 600);
  };

  const detectCategory = (filename) => {
    const lower = filename.toLowerCase();
    if (lower.includes("gst") || lower.includes("abn") || lower.includes("trn") || lower.includes("tax")) {
      return CATEGORIES.GST;
    }
    if (lower.includes("pan") || lower.includes("id")) {
      return CATEGORIES.PAN;
    }
    return CATEGORIES.CONTRACT;
  };

  const processUploadedFiles = (uploadedFileList) => {
    const newFileEntries = [];

    Array.from(uploadedFileList).forEach((rawFile) => {
      const ext = rawFile.name.split('.').pop().toLowerCase();
      if (!['pdf', 'jpg', 'jpeg', 'png', 'docx'].includes(ext)) {
        addToast("error", "Unsupported File Type", `"${rawFile.name}" is not supported.`);
        return;
      }

      const fileId = "doc-" + Date.now() + "-" + Math.random().toString(36).substring(2, 7);
      const sizeFormatted = (rawFile.size / (1024 * 1024)).toFixed(2) + " MB";
      const initialCat = detectCategory(rawFile.name);

      const fileItem = {
        id: fileId,
        name: rawFile.name,
        size: sizeFormatted,
        type: ext === 'jpeg' ? 'jpg' : ext,
        rawFile: rawFile,
        status: "Uploaded",
        category: initialCat,
        uploadTime: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        fileDataUrl: URL.createObjectURL(rawFile)
      };

      newFileEntries.push(fileItem);
      simulateDocumentExtraction(fileId, initialCat, rawFile.name);
    });

    if (newFileEntries.length > 0) {
      setFiles((prev) => [...prev, ...newFileEntries]);
      addToast("info", "Upload Started", `Uploaded ${newFileEntries.length} file(s). Extracting data...`);
    }
  };

  const handleCategoryChange = (fileId, newCategory) => {
    const targetFile = files.find(f => f.id === fileId);
    setFiles((prev) =>
      prev.map((f) => (f.id === fileId ? { ...f, category: newCategory } : f))
    );
    if (targetFile) {
      simulateDocumentExtraction(fileId, newCategory, targetFile.name);
    }
  };

  const handleRemoveFile = (fileId) => {
    const fileToRemove = files.find((f) => f.id === fileId);
    setFiles((prev) => prev.filter((f) => f.id !== fileId));
    if (fileToRemove) {
      addToast("info", "Document Removed", `Removed "${fileToRemove.name}".`);
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      processUploadedFiles(e.dataTransfer.files);
    }
  };

  const handleSaveDraft = () => {
    setIsSaving(true);
    setTimeout(() => {
      setIsSaving(false);
      const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      setLastSaved(`Saved at ${timeStr}`);
      addToast("success", "Draft Saved", "Form values persisted.");
    }, 500);
  };

  const handleSubmitPortal = () => {
    if (!isFormValid) {
      addToast("error", "Validation Required", "Please complete all mandatory fields.");
      return;
    }
    setShowSubmitModal(true);
  };

  const handleConfirmFinalSubmit = () => {
    setShowSubmitModal(false);
    if (window.confetti) {
      window.confetti({ particleCount: 120, spread: 70, origin: { y: 0.6 } });
    }
    addToast("success", "🎉 Submitted Successfully!", "Data submitted to Business Central.");
  };

  const gstDoc = useMemo(() => files.find((f) => f.category === CATEGORIES.GST), [files]);
  const panDoc = useMemo(() => files.find((f) => f.category === CATEGORIES.PAN), [files]);
  const contractDocs = useMemo(() => files.filter((f) => f.category === CATEGORIES.CONTRACT), [files]);

  // Reusable Input Field Component (non-grouped list render)
  const renderInputField = (label, name, required = false, type = "text") => {
    const isAutoFilled = autoFilledFields[name];
    const hasError = validationErrors[name];

    return (
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <label className="text-xs font-semibold text-slate-700 flex items-center space-x-1">
            <span>{label}</span>
            {required && <span className="text-red-500">*</span>}
          </label>

          {isAutoFilled && (
            <div className="flex items-center space-x-1 bg-emerald-50 text-emerald-700 text-[10px] font-medium px-2 py-0.5 rounded border border-emerald-200">
              <Icon name="sparkles" className="w-3 h-3 text-emerald-600" />
              <span>Auto-filled</span>
              <button
                type="button"
                onClick={() => handleReExtractField(name)}
                className="ml-1 text-slate-400 hover:text-emerald-700"
                title="Re-extract value"
              >
                <Icon name="refresh-cw" className="w-3 h-3" />
              </button>
            </div>
          )}
        </div>

        {type === "textarea" ? (
          <textarea
            rows="2"
            value={formData[name]}
            onChange={(e) => handleInputChange(name, e.target.value)}
            placeholder={`Enter ${label}`}
            className={`w-full text-sm bg-white border rounded-lg px-3.5 py-2.5 text-slate-800 bc-input ${
              isAutoFilled ? "autofill-active border-emerald-400" : "border-slate-300"
            } ${hasError ? "border-red-500" : ""}`}
          ></textarea>
        ) : (
          <input
            type={type}
            value={formData[name]}
            onChange={(e) => handleInputChange(name, e.target.value)}
            placeholder={`Enter ${label}`}
            className={`w-full text-sm bg-white border rounded-lg px-3.5 py-2.5 text-slate-800 bc-input ${
              isAutoFilled ? "autofill-active border-emerald-400" : "border-slate-300"
            } ${hasError ? "border-red-500" : ""}`}
          />
        )}

        {hasError && (
          <p className="text-xs text-red-500 mt-1 flex items-center space-x-1">
            <Icon name="alert-circle" className="w-3 h-3" />
            <span>{hasError}</span>
          </p>
        )}
      </div>
    );
  };

  return (
    <div className="min-h-screen flex flex-col bg-[#f4f6f9]">
      
      {/* TOP BAR */}
      <header className="bc-glass-header sticky top-0 z-40 border-b border-slate-200 px-4 lg:px-8 py-3 flex items-center justify-between shadow-bc-sm">
        <div className="flex items-center space-x-3">
          <div className="w-9 h-9 rounded-lg bg-bc-700 flex items-center justify-center text-white font-bold shadow-md">
            <Icon name="building-2" className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h1 className="font-bold text-slate-800 text-base lg:text-lg tracking-tight">
                Business Central Document Intake Portal
              </h1>
            </div>
            <p className="text-xs text-slate-500 hidden sm:block">
              Document Upload & Automated Field Intake
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-3">
          <div className="hidden md:flex items-center text-xs text-slate-500 space-x-1.5 bg-slate-100 px-3 py-1.5 rounded-md border border-slate-200">
            <Icon name="clock" className="w-3.5 h-3.5 text-slate-400" />
            <span>Draft Status: <strong className="text-slate-700">{lastSaved}</strong></span>
          </div>

          <button
            onClick={handleSaveDraft}
            disabled={isSaving}
            className="flex items-center space-x-1.5 bg-white text-slate-700 hover:bg-slate-50 text-xs sm:text-sm font-medium px-3.5 py-2 rounded-md border border-slate-300 shadow-sm transition-all"
          >
            <Icon name="save" className={`w-4 h-4 ${isSaving ? 'animate-spin text-bc-600' : 'text-slate-500'}`} />
            <span>{isSaving ? "Saving..." : "Save Draft"}</span>
          </button>

          <button
            onClick={handleSubmitPortal}
            disabled={!isFormValid}
            className={`flex items-center space-x-1.5 text-xs sm:text-sm font-semibold px-4 py-2 rounded-md shadow-sm transition-all ${
              isFormValid
                ? "bg-bc-700 hover:bg-bc-800 text-white shadow-bc-sm"
                : "bg-slate-200 text-slate-400 cursor-not-allowed border border-slate-300"
            }`}
          >
            <Icon name="send" className="w-4 h-4" />
            <span>Submit</span>
          </button>
        </div>
      </header>

      {/* MAIN CONTAINER: TWO PANELS */}
      <main className="flex-1 max-w-[1600px] w-full mx-auto p-4 lg:p-6 grid grid-cols-1 lg:grid-cols-12 gap-6 items-start mb-20">
        
        {/* LEFT PANEL: DOCUMENT UPLOAD */}
        <section className={`lg:col-span-5 bg-white rounded-xl border border-slate-200 shadow-bc-sm overflow-hidden flex flex-col ${isUploadPanelCollapsed ? 'h-auto' : ''}`}>
          <div className="p-4 sm:p-5 border-b border-slate-100 bg-slate-50/50 flex items-center justify-between">
            <div className="flex items-center space-x-2.5">
              <div className="p-2 bg-bc-50 rounded-lg text-bc-700 border border-bc-100">
                <Icon name="upload-cloud" className="w-5 h-5" />
              </div>
              <div>
                <h2 className="font-semibold text-slate-800 text-base">Document Upload</h2>
                <p className="text-xs text-slate-500">Drag and drop or browse files</p>
              </div>
            </div>

            <div className="flex items-center space-x-2">
              <span className="text-xs bg-slate-200 text-slate-700 font-semibold px-2.5 py-1 rounded-full">
                {files.length} {files.length === 1 ? 'file' : 'files'}
              </span>
              <button 
                onClick={() => setIsUploadPanelCollapsed(!isUploadPanelCollapsed)}
                className="lg:hidden p-1.5 text-slate-500 hover:bg-slate-200 rounded-md"
              >
                <Icon name={isUploadPanelCollapsed ? "chevron-down" : "chevron-up"} className="w-4 h-4" />
              </button>
            </div>
          </div>

          {!isUploadPanelCollapsed && (
            <div className="p-4 sm:p-5 space-y-5">
              
              {/* DRAG & DROP ZONE */}
              <div
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current && fileInputRef.current.click()}
                className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all duration-200 flex flex-col items-center justify-center space-y-3 relative group ${
                  isDragging
                    ? "dropzone-active"
                    : "border-slate-300 bg-slate-50/60 hover:bg-bc-50/40 hover:border-bc-400"
                }`}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept=".pdf,.jpg,.jpeg,.png,.docx"
                  className="hidden"
                  onChange={(e) => e.target.files && processUploadedFiles(e.target.files)}
                />

                <div className="w-12 h-12 rounded-full bg-white shadow-sm border border-slate-200 flex items-center justify-center text-bc-600 group-hover:scale-110 transition-transform">
                  <Icon name="file-plus" className="w-6 h-6" />
                </div>

                <div>
                  <p className="text-sm font-semibold text-slate-700">
                    <span className="text-bc-700 hover:underline">Browse files</span> or drag & drop here
                  </p>
                  <p className="text-xs text-slate-400 mt-1">
                    PDF, JPG, PNG, DOCX accepted
                  </p>
                </div>
              </div>

              {/* UPLOADED FILE CARDS */}
              <div className="space-y-3">
                <h4 className="text-xs font-semibold text-slate-500">Uploaded File Cards</h4>

                {files.length === 0 ? (
                  <div className="py-8 text-center border border-dashed border-slate-200 rounded-lg">
                    <Icon name="file-question" className="w-8 h-8 text-slate-300 mx-auto mb-2" />
                    <p className="text-sm text-slate-500 font-medium">No documents attached</p>
                    <p className="text-xs text-slate-400">Upload a document to trigger automatic field extraction</p>
                  </div>
                ) : (
                  <div className="space-y-3 max-h-[500px] overflow-y-auto pr-1">
                    {files.map((file) => {
                      const isPDF = file.type === "pdf";
                      const isImage = file.type === "jpg" || file.type === "png";
                      const isDocx = file.type === "docx";

                      return (
                        <div
                          key={file.id}
                          className="bg-slate-50 hover:bg-slate-100/90 border border-slate-200 rounded-lg p-3.5 transition-all shadow-sm space-y-3"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="flex items-start space-x-3 min-w-0">
                              <div className={`w-9 h-9 rounded-md flex items-center justify-center shrink-0 text-white font-bold text-xs ${
                                isPDF ? "bg-red-500" : isImage ? "bg-emerald-500" : isDocx ? "bg-blue-600" : "bg-slate-600"
                              }`}>
                                {isPDF && <Icon name="file-text" className="w-5 h-5" />}
                                {isImage && <Icon name="image" className="w-5 h-5" />}
                                {isDocx && <Icon name="file-spreadsheet" className="w-5 h-5" />}
                              </div>

                              <div className="min-w-0">
                                <h4 className="text-sm font-semibold text-slate-800 truncate" title={file.name}>
                                  {file.name}
                                </h4>
                                <p className="text-xs text-slate-500 mt-0.5">{file.size}</p>
                              </div>
                            </div>

                            <div className="flex items-center space-x-1 shrink-0">
                              <button
                                onClick={() => setActivePreviewFile(file)}
                                className="p-1.5 text-slate-400 hover:text-bc-700 hover:bg-white rounded"
                                title="Preview Document"
                              >
                                <Icon name="eye" className="w-4 h-4" />
                              </button>
                              <button
                                onClick={() => handleRemoveFile(file.id)}
                                className="p-1.5 text-slate-400 hover:text-red-600 hover:bg-white rounded"
                                title="Remove File"
                              >
                                <Icon name="x" className="w-4 h-4" />
                              </button>
                            </div>
                          </div>

                          <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-200/60">
                            <div className="flex items-center space-x-1.5">
                              <Icon name="tag" className="w-3.5 h-3.5 text-slate-400" />
                              <select
                                value={file.category}
                                onChange={(e) => handleCategoryChange(file.id, e.target.value)}
                                className="text-xs bg-white border border-slate-300 rounded px-2 py-1 text-slate-700 font-medium outline-none"
                              >
                                <option value={CATEGORIES.GST}>{CATEGORIES.GST}</option>
                                <option value={CATEGORIES.PAN}>{CATEGORIES.PAN}</option>
                                <option value={CATEGORIES.CONTRACT}>{CATEGORIES.CONTRACT}</option>
                              </select>
                            </div>

                            <div>
                              {file.status === "Uploaded" && (
                                <span className="inline-flex items-center space-x-1 text-[11px] font-medium bg-slate-200 text-slate-700 px-2 py-0.5 rounded-full">
                                  <Icon name="clock" className="w-3 h-3 text-slate-500" />
                                  <span>Uploaded</span>
                                </span>
                              )}

                              {file.status === "Extracting" && (
                                <span className="inline-flex items-center space-x-1 text-[11px] font-semibold bg-bc-100 text-bc-800 px-2 py-0.5 rounded-full animate-pulse border border-bc-200">
                                  <Icon name="loader-2" className="w-3 h-3 animate-spin text-bc-600" />
                                  <span>Extracting...</span>
                                </span>
                              )}

                              {file.status === "Mapped" && (
                                <span className="inline-flex items-center space-x-1 text-[11px] font-semibold bg-emerald-100 text-emerald-800 px-2 py-0.5 rounded-full border border-emerald-200">
                                  <Icon name="check-circle-2" className="w-3 h-3 text-emerald-600" />
                                  <span>Mapped</span>
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

            </div>
          )}
        </section>

        {/* RIGHT PANEL: FORM FIELDS (UNGROUPED SINGLE LIST) */}
        <section className="lg:col-span-7 bg-white rounded-xl border border-slate-200 shadow-bc-sm p-5 lg:p-7 space-y-5">
          
          <div className="pb-3 border-b border-slate-100">
            <h2 className="text-lg font-bold text-slate-800">Form Fields</h2>
            <p className="text-xs text-slate-500">All fields listed cleanly without grouping headers</p>
          </div>

          {/* 1. Company Name */}
          {renderInputField("Company Name", "companyName", true)}

          {/* 2. Contact Name */}
          {renderInputField("Contact Name", "contactName", true)}

          {/* 3. Billing Address */}
          {renderInputField("Billing Address", "billingAddress", true, "textarea")}

          {/* 4. City */}
          {renderInputField("City", "city", true)}

          {/* 5. State */}
          {renderInputField("State", "state", true)}

          {/* 6. Zip code / Pin code */}
          {renderInputField("Zip code / Pin code", "zipCode", true)}

          {/* 7. Country (Text Input - NO Dropdown as requested) */}
          {renderInputField("Country", "country", true)}

          {/* 8. GST (ABN, TRN) Registration Certificate (Upload Attachment Linked View) */}
          <div className="space-y-1.5 pt-1">
            <label className="text-xs font-semibold text-slate-700 block">
              GST (ABN, TRN) Registration Certificate
            </label>

            {gstDoc ? (
              <div className="bg-emerald-50/60 border border-emerald-300 rounded-lg p-3 flex items-center justify-between">
                <div className="flex items-center space-x-2.5 min-w-0">
                  <Icon name="file-check-2" className="w-4 h-4 text-emerald-700 shrink-0" />
                  <span className="text-xs font-semibold text-slate-800 truncate">{gstDoc.name}</span>
                </div>
                <button
                  type="button"
                  onClick={() => setActivePreviewFile(gstDoc)}
                  className="text-xs text-bc-700 font-medium hover:underline shrink-0 ml-2"
                >
                  Preview Document
                </button>
              </div>
            ) : (
              <div className="border border-slate-200 rounded-lg p-3 bg-slate-50 flex items-center justify-between">
                <span className="text-xs text-slate-500">No document attached</span>
                <button
                  type="button"
                  onClick={() => fileInputRef.current && fileInputRef.current.click()}
                  className="text-xs bg-white text-bc-700 border border-slate-300 hover:border-bc-500 font-medium px-3 py-1.5 rounded transition-all inline-flex items-center space-x-1"
                >
                  <Icon name="upload" className="w-3.5 h-3.5" />
                  <span>Upload GST Certificate</span>
                </button>
              </div>
            )}
          </div>

          {/* 9. PAN Card (Company/Individual) (Upload Attachment Linked View) */}
          <div className="space-y-1.5 pt-1">
            <label className="text-xs font-semibold text-slate-700 block">
              PAN Card (Company/Individual)
            </label>

            {panDoc ? (
              <div className="bg-emerald-50/60 border border-emerald-300 rounded-lg p-3 flex items-center justify-between">
                <div className="flex items-center space-x-2.5 min-w-0">
                  <Icon name="file-check-2" className="w-4 h-4 text-emerald-700 shrink-0" />
                  <span className="text-xs font-semibold text-slate-800 truncate">{panDoc.name}</span>
                </div>
                <button
                  type="button"
                  onClick={() => setActivePreviewFile(panDoc)}
                  className="text-xs text-bc-700 font-medium hover:underline shrink-0 ml-2"
                >
                  Preview Document
                </button>
              </div>
            ) : (
              <div className="border border-slate-200 rounded-lg p-3 bg-slate-50 flex items-center justify-between">
                <span className="text-xs text-slate-500">No document attached</span>
                <button
                  type="button"
                  onClick={() => fileInputRef.current && fileInputRef.current.click()}
                  className="text-xs bg-white text-bc-700 border border-slate-300 hover:border-bc-500 font-medium px-3 py-1.5 rounded transition-all inline-flex items-center space-x-1"
                >
                  <Icon name="upload" className="w-3.5 h-3.5" />
                  <span>Upload PAN Card</span>
                </button>
              </div>
            )}
          </div>

          {/* 10. Email ID TO */}
          {renderInputField("Email ID TO", "emailTo", true, "email")}

          {/* 11. Email ID CC (Multi-chip Tag Input) */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-700 block">
              Email ID CC
            </label>

            <div className="border border-slate-300 rounded-lg p-2 bg-white focus-within:ring-2 focus-within:ring-bc-500 focus-within:border-bc-500 transition-all flex flex-wrap items-center gap-1.5 min-h-[44px]">
              {formData.emailCc.map((email) => (
                <span
                  key={email}
                  className="inline-flex items-center space-x-1.5 bg-bc-50 text-bc-800 border border-bc-200 text-xs font-medium px-2.5 py-1 rounded-full"
                >
                  <span>{email}</span>
                  <button
                    type="button"
                    onClick={() => handleRemoveCcEmail(email)}
                    className="text-bc-600 hover:text-red-600 rounded-full p-0.5"
                  >
                    <Icon name="x" className="w-3 h-3" />
                  </button>
                </span>
              ))}

              <input
                type="email"
                value={ccInputValue}
                onChange={(e) => {
                  setCcInputValue(e.target.value);
                  setCcError("");
                }}
                onKeyDown={handleAddCcEmail}
                placeholder={formData.emailCc.length === 0 ? "Type email and press Enter or comma..." : "Add another..."}
                className="flex-1 min-w-[200px] text-sm outline-none bg-transparent py-1 px-1 text-slate-800 placeholder:text-slate-400"
              />
            </div>
            {ccError && <p className="text-xs text-red-500 mt-1">{ccError}</p>}
          </div>

          {/* 12. Phone Number (Text Input - NO Prefix Dropdown as requested) */}
          {renderInputField("Phone Number", "phoneNumber", true)}

          {/* 13. Payment Terms (Text Input - NO Dropdown as requested) */}
          {renderInputField("Payment Terms", "paymentTerms")}

          {/* 14. SALESPERSON (Text Input - NO Dropdown as requested) */}
          {renderInputField("SALESPERSON", "salesperson")}

          {/* 15. REGION (Text Input - NO Dropdown as requested) */}
          {renderInputField("REGION", "region")}

          {/* 16. Customer Agreement / Contract / Purchase Order / Sale Order (File Attachment Area) */}
          <div className="space-y-1.5 pt-1">
            <label className="text-xs font-semibold text-slate-700 block">
              Customer Agreement / Contract / Purchase Order / Sale Order
            </label>

            {contractDocs.length > 0 ? (
              <div className="space-y-2">
                {contractDocs.map((doc) => (
                  <div
                    key={doc.id}
                    className="bg-slate-50 border border-slate-200 rounded-lg p-3 flex items-center justify-between"
                  >
                    <div className="flex items-center space-x-2.5 min-w-0">
                      <Icon name="file-text" className="w-4 h-4 text-bc-700 shrink-0" />
                      <span className="text-xs font-semibold text-slate-800 truncate">{doc.name}</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => setActivePreviewFile(doc)}
                      className="text-xs text-bc-700 font-medium hover:underline shrink-0 ml-2"
                    >
                      Preview
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="border border-slate-200 rounded-lg p-3 bg-slate-50 flex items-center justify-between">
                <span className="text-xs text-slate-500">Requires uploading document</span>
                <button
                  type="button"
                  onClick={() => fileInputRef.current && fileInputRef.current.click()}
                  className="text-xs bg-white text-bc-700 border border-slate-300 hover:border-bc-500 font-medium px-3 py-1.5 rounded transition-all inline-flex items-center space-x-1"
                >
                  <Icon name="upload" className="w-3.5 h-3.5" />
                  <span>Upload Document</span>
                </button>
              </div>
            )}
          </div>

          {/* 17. Type (Dropdown for Services / License ONLY) */}
          <div className="space-y-1.5 pt-1">
            <label className="text-xs font-semibold text-slate-700 block">
              Type
            </label>
            <select
              value={formData.type}
              onChange={(e) => handleInputChange("type", e.target.value)}
              className="w-full text-sm bg-white border border-slate-300 rounded-lg px-3.5 py-2.5 text-slate-800 bc-input"
            >
              <option value="">Select Type...</option>
              <option value="Services">Services</option>
              <option value="License">License</option>
            </select>
          </div>

        </section>

      </main>

      {/* STICKY FOOTER ACTION BAR */}
      <footer className="fixed bottom-0 left-0 right-0 z-30 bg-white/95 backdrop-blur-md border-t border-slate-200 px-4 lg:px-8 py-3.5 shadow-lg">
        <div className="max-w-[1600px] mx-auto flex flex-col sm:flex-row items-center justify-between gap-3">
          
          <div className="flex items-center space-x-3 w-full sm:w-auto justify-between sm:justify-start">
            <div className="flex items-center space-x-2">
              <div className={`w-3 h-3 rounded-full ${isFormValid ? 'bg-emerald-500' : 'bg-amber-500'}`}></div>
              <span className="text-xs font-medium text-slate-700">
                {isFormValid ? "Form Validation Clean" : "Required fields pending"}
              </span>
            </div>

            <span className="text-slate-300 hidden sm:inline">|</span>

            <span className="text-xs text-slate-500">
              Auto-filled active: <strong className="text-emerald-700 font-semibold">{Object.keys(autoFilledFields).length}</strong>
            </span>
          </div>

          <div className="flex items-center space-x-3 w-full sm:w-auto justify-end">
            <button
              onClick={handleSaveDraft}
              disabled={isSaving}
              className="flex-1 sm:flex-none text-xs sm:text-sm font-semibold text-slate-700 bg-slate-100 hover:bg-slate-200 border border-slate-300 px-4 py-2 rounded-lg transition-all"
            >
              {isSaving ? "Saving..." : "Save Draft"}
            </button>

            <button
              onClick={handleSubmitPortal}
              disabled={!isFormValid}
              className={`flex-1 sm:flex-none text-xs sm:text-sm font-semibold px-5 py-2 rounded-lg transition-all shadow-sm flex items-center justify-center space-x-2 ${
                isFormValid
                  ? "bg-bc-700 hover:bg-bc-800 text-white"
                  : "bg-slate-200 text-slate-400 cursor-not-allowed border border-slate-300"
              }`}
            >
              <Icon name="check-circle" className="w-4 h-4" />
              <span>Submit</span>
            </button>
          </div>

        </div>
      </footer>

      {/* PREVIEW MODAL */}
      {activePreviewFile && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-2xl max-w-2xl w-full overflow-hidden border border-slate-200 flex flex-col max-h-[85vh]">
            
            <div className="p-4 bg-slate-800 text-white flex items-center justify-between">
              <div className="flex items-center space-x-3 min-w-0">
                <Icon name="file-text" className="w-5 h-5 text-bc-300 shrink-0" />
                <div className="min-w-0">
                  <h3 className="font-semibold text-sm truncate">{activePreviewFile.name}</h3>
                  <p className="text-xs text-slate-400">{activePreviewFile.category} • {activePreviewFile.size}</p>
                </div>
              </div>

              <button
                onClick={() => setActivePreviewFile(null)}
                className="p-1 text-slate-400 hover:text-white rounded-md"
              >
                <Icon name="x" className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 flex-1 overflow-y-auto bg-slate-100 flex flex-col items-center justify-center min-h-[300px]">
              {activePreviewFile.type === 'jpg' || activePreviewFile.type === 'png' ? (
                <img
                  src={activePreviewFile.fileDataUrl}
                  alt="Document Preview"
                  className="max-h-[400px] object-contain rounded-lg border border-slate-300 shadow-md"
                />
              ) : (
                <div className="bg-white p-8 rounded-xl border border-slate-200 shadow-md max-w-md w-full text-center space-y-4">
                  <div className="w-16 h-16 rounded-full bg-bc-50 text-bc-700 flex items-center justify-center mx-auto">
                    <Icon name="file-search" className="w-8 h-8" />
                  </div>
                  <div>
                    <h4 className="font-bold text-slate-800 text-base">{activePreviewFile.name}</h4>
                    <p className="text-xs text-slate-500 mt-1">Document Attachment Preview</p>
                  </div>
                </div>
              )}
            </div>

            <div className="p-3 bg-white border-t border-slate-200 flex justify-end">
              <button
                onClick={() => setActivePreviewFile(null)}
                className="px-4 py-2 text-xs font-semibold bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-md"
              >
                Close Preview
              </button>
            </div>

          </div>
        </div>
      )}

      {/* SUBMISSION MODAL */}
      {showSubmitModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-2xl max-w-md w-full overflow-hidden border border-slate-200">
            
            <div className="p-5 bg-bc-800 text-white flex items-center justify-between">
              <div className="flex items-center space-x-2.5">
                <Icon name="shield-check" className="w-6 h-6 text-emerald-400" />
                <h3 className="font-bold text-base">Confirm Submission</h3>
              </div>
              <button onClick={() => setShowSubmitModal(false)} className="text-slate-300 hover:text-white">
                <Icon name="x" className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 space-y-4 max-h-[70vh] overflow-y-auto text-xs text-slate-700">
              <p>Ready to submit to Business Central with the following data:</p>

              <div className="bg-slate-50 p-4 rounded-lg border border-slate-200 space-y-1.5">
                <p><strong>Company:</strong> {formData.companyName}</p>
                <p><strong>Contact:</strong> {formData.contactName}</p>
                <p><strong>City / Country:</strong> {formData.city}, {formData.country}</p>
                <p><strong>Email TO:</strong> {formData.emailTo}</p>
                <p><strong>Type:</strong> {formData.type || "Not selected"}</p>
                <p><strong>Attached Docs:</strong> {files.length} file(s)</p>
              </div>
            </div>

            <div className="p-4 bg-slate-50 border-t border-slate-200 flex items-center justify-end space-x-3">
              <button
                onClick={() => setShowSubmitModal(false)}
                className="px-4 py-2 text-xs font-semibold bg-white border border-slate-300 text-slate-700 rounded-lg hover:bg-slate-100"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmFinalSubmit}
                className="px-5 py-2 text-xs font-semibold bg-bc-700 hover:bg-bc-800 text-white rounded-lg shadow-sm"
              >
                Confirm & Submit
              </button>
            </div>

          </div>
        </div>
      )}

      {/* TOAST CONTAINER */}
      <div className="fixed top-4 right-4 z-50 space-y-2 max-w-sm w-full pointer-events-none">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`pointer-events-auto p-3.5 rounded-lg shadow-bc-lg border flex items-start space-x-3 transition-all ${
              toast.type === "success"
                ? "bg-white border-emerald-300 text-slate-800"
                : toast.type === "error"
                ? "bg-white border-red-300 text-slate-800"
                : "bg-slate-900 border-slate-700 text-white"
            }`}
          >
            <div className="shrink-0 mt-0.5">
              {toast.type === "success" && <Icon name="check-circle-2" className="w-5 h-5 text-emerald-600" />}
              {toast.type === "error" && <Icon name="alert-triangle" className="w-5 h-5 text-red-500" />}
              {toast.type === "info" && <Icon name="info" className="w-5 h-5 text-bc-400" />}
            </div>

            <div className="flex-1 min-w-0">
              <h4 className="text-xs font-bold leading-snug">{toast.title}</h4>
              <p className="text-[11px] opacity-90 mt-0.5">{toast.message}</p>
            </div>

            <button
              onClick={() => removeToast(toast.id)}
              className="text-slate-400 hover:text-slate-600 shrink-0"
            >
              <Icon name="x" className="w-4 h-4" />
            </button>
          </div>
        ))}
      </div>

    </div>
  );
}

// Render React Root
const rootElement = document.getElementById("root");
const root = ReactDOM.createRoot(rootElement);
root.render(<App />);
