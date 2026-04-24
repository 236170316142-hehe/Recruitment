const express = require("express");
const FormData = require("form-data");

const { apiClient } = require("../services/apiClient");
const { upload } = require("../middleware/upload");

const router = express.Router();

function getAuthToken(req) {
  const headerToken = req.headers.authorization?.replace('Bearer ', '');
  if (headerToken) {
    return headerToken;
  }

  const cookieHeader = req.headers.cookie || '';
  const cookieMatch = cookieHeader.match(/(?:^|; )auth_token=([^;]+)/);
  return cookieMatch ? decodeURIComponent(cookieMatch[1]) : null;
}

// ============================================================================
// MIDDLEWARE
// ============================================================================

// Check if user is authenticated
function requireAuth(req, res, next) {
  const authToken = getAuthToken(req);
  if (!authToken) {
    return res.redirect('/login');
  }
  next();
}

// Add userProfile to all routes
async function addUserProfile(req, res, next) {
  const token = getAuthToken(req);
  if (token) {
    try {
      const response = await apiClient.get('/auth/profile', {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      res.locals.userProfile = response.data;
    } catch (error) {
      // User data not available
    }
  }
  next();
}

// ============================================================================
// LOGIN PAGE
// ============================================================================

router.get("/login", (req, res) => {
  res.render("pages/login", {
    GOOGLE_CLIENT_ID: process.env.GOOGLE_CLIENT_ID,
    BACKEND_API_BASE: process.env.BACKEND_API_BASE
  });
});

// ============================================================================
// GOOGLE OAUTH CALLBACK
// ============================================================================

router.get("/auth/google/callback", async (req, res) => {
  try {
    const { code, state } = req.query;
    
    if (!code) {
      return res.status(400).render("pages/login", {
        error: "Authorization failed"
      });
    }
    
    // Frontend receives code, frontend sends it to backend
    // This is handled by JavaScript in browser, so just show success page
    res.render("pages/login-success", {
      message: "Gmail account connected! Redirecting to dashboard..."
    });
  } catch (error) {
    res.status(500).render("pages/login", {
      error: "Failed to process authorization"
    });
  }
});

// ============================================================================
// JOBS PAGE
// ============================================================================

router.get("/", requireAuth, addUserProfile, async (req, res) => {
  try {
    const token = getAuthToken(req);
    const { data } = await apiClient.get("/jobs", {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {}
    });
    res.render("layout", {
      page: "jobs",
      jobs: data.jobs || [],
      jobId: null,
      userProfile: res.locals.userProfile,
    });
  } catch (error) {
    res.render("layout", {
      page: "jobs",
      jobs: [],
      jobId: null,
      userProfile: res.locals.userProfile,
      error: "Could not fetch jobs",
    });
  }
});

router.post("/jobs/create", requireAuth, upload.single("file"), async (req, res) => {
  try {
    const token = getAuthToken(req);
    const form = new FormData();
    if (req.body.text) {
      form.append("text", req.body.text);
    }
    if (req.file) {
      form.append("file", req.file.buffer, { filename: req.file.originalname });
    }

    const headers = form.getHeaders();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const { data } = await apiClient.post("/jobs", form, { headers });
    return res.redirect(`/?jobId=${data.job_id}`);
  } catch (error) {
    const errorMsg = error.response?.data?.detail 
      || error.response?.data?.message 
      || error.message 
      || "Job creation failed";
    const status = error.response?.status || 500;
    
    console.error(`Job creation error [${status}]:`, errorMsg);
    
    return res.status(400).render("layout", {
      page: "jobs",
      jobs: [],
      userProfile: res.locals.userProfile,
      error: `Error (${status}): ${errorMsg}`,
    });
  }
});

// ============================================================================
// RESUMES PAGE
// ============================================================================

router.get("/resumes", requireAuth, addUserProfile, async (req, res) => {
  const { jobId } = req.query;
  const token = getAuthToken(req);

  try {
    const { data: jobsData } = await apiClient.get("/jobs", {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {}
    });
    const availableJobs = jobsData.jobs || [];

    if (!jobId) {
      return res.render("layout", {
        page: "resumes",
        availableJobs,
        jobId: null,
        selectedJobId: null,
        userProfile: res.locals.userProfile,
      });
    }

    const { data: jobData } = await apiClient.get(`/jobs/${jobId}`, {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {}
    });
    const { data: resumesData } = await apiClient.get(`/resumes/${jobId}`, {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {}
    });

    return res.render("layout", {
      page: "resumes",
      availableJobs,
      jobId: jobId,
      selectedJobId: jobId,
      job: jobData,
      resumes: resumesData.resumes || [],
      userProfile: res.locals.userProfile,
      uploaded: req.query.uploaded,
      skipped: req.query.skipped,
    });
  } catch (error) {
    return res.render("layout", {
      page: "resumes",
      availableJobs: [],
      jobId: jobId,
      selectedJobId: jobId,
      userProfile: res.locals.userProfile,
      error: "Could not fetch data",
    });
  }
});

router.post("/resumes/upload", requireAuth, upload.array("resumes", 50), async (req, res) => {
  const { jobId, source = "manual" } = req.body;
  const token = getAuthToken(req);

  if (!jobId) {
    return res.status(400).render("layout", {
      page: "resumes",
      availableJobs: [],
      userProfile: res.locals.userProfile,
      error: "Job ID required",
    });
  }

  try {
    const form = new FormData();
    form.append("job_id", jobId);
    form.append("source", source);

    for (const file of req.files || []) {
      form.append("files", file.buffer, { filename: file.originalname });
    }

    const headers = form.getHeaders();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const { data } = await apiClient.post("/resumes/upload", form, { headers });

    return res.redirect(`/resumes?jobId=${jobId}&uploaded=${data.uploaded_count}&skipped=${data.skipped_count || 0}`);
  } catch (error) {
    return res.status(400).render("layout", {
      page: "resumes",
      availableJobs: [],
      selectedJobId: jobId,
      userProfile: res.locals.userProfile,
      error: error.response?.data?.detail || "Resume upload failed",
    });
  }
});

router.post("/resumes/fetch-gmail", requireAuth, async (req, res) => {
  const { jobId } = req.body;
  const token = getAuthToken(req);

  if (!jobId) {
    return res.status(400).json({ error: "Job ID required" });
  }

  try {
    const form = new FormData();
    form.append("job_id", jobId);

    const headers = form.getHeaders();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const { data } = await apiClient.post("/resumes/fetch-gmail", form, { headers });
    return res.json({ 
      success: true, 
      count: data.uploaded_count,
      redirect: `/resumes?jobId=${jobId}&uploaded=${data.uploaded_count}`
    });
  } catch (error) {
    console.error("Gmail fetch error:", error.response?.data || error.message);
    return res.status(400).json({ 
      error: error.response?.data?.detail || "Gmail fetch failed" 
    });
  }
});

// ============================================================================
// DASHBOARD PAGE
// ============================================================================

router.get("/dashboard", requireAuth, addUserProfile, async (req, res) => {
  let { jobId, confidence, source, search } = req.query;
  const token = getAuthToken(req);

  // Default to HIGH confidence if not specified
  if (!confidence && jobId) {
    confidence = 'HIGH';
  }

  try {
    const { data: jobsData } = await apiClient.get("/jobs", {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {}
    });
    const availableJobs = jobsData.jobs || [];

    if (!jobId) {
      return res.render("layout", {
        page: "dashboard",
        availableJobs,
        jobId: null,
        selectedJobId: null,
        dashboard: null,
        userProfile: res.locals.userProfile,
      });
    }

    let dashboardUrl = `/dashboard/${jobId}`;
    const params = [];
    if (confidence) params.push(`confidence=${confidence}`);
    if (source) params.push(`source=${source}`);
    if (search) params.push(`search=${search}`);
    if (params.length > 0) dashboardUrl += "?" + params.join("&");

    const { data: dashboard } = await apiClient.get(dashboardUrl, {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {}
    });

    return res.render("layout", {
      page: "dashboard",
      availableJobs,
      jobId: jobId,
      selectedJobId: jobId,
      dashboard,
      userProfile: res.locals.userProfile,
    });
  } catch (error) {
    return res.render("layout", {
      page: "dashboard",
      availableJobs: [],
      jobId: jobId,
      selectedJobId: jobId,
      dashboard: null,
      userProfile: res.locals.userProfile,
      error: error.response?.data?.detail || "Could not fetch dashboard",
    });
  }
});

// ============================================================================
// CANDIDATE DETAIL PAGE
// ============================================================================

router.get("/candidate/:resumeId", requireAuth, addUserProfile, async (req, res) => {
  const { resumeId } = req.params;
  const token = getAuthToken(req);

  try {
    const { data: candidate } = await apiClient.get(`/candidate/${resumeId}`, {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {}
    });
    const { data: jobsData } = await apiClient.get("/jobs", {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {}
    });

    return res.render("layout", {
      page: "candidate",
      candidate,
      availableJobs: jobsData.jobs || [],
      userProfile: res.locals.userProfile,
    });
  } catch (error) {
    return res.status(404).render("layout", {
      page: "candidate",
      candidate: null,
      userProfile: res.locals.userProfile,
      error: "Candidate not found",
    });
  }
});

// ============================================================================
// API ENDPOINTS (for AJAX calls)
// ============================================================================

router.delete("/api/jobs/:jobId", requireAuth, async (req, res) => {
  const { jobId } = req.params;
  const token = getAuthToken(req);

  try {
    const { data } = await apiClient.delete(`/jobs/${jobId}`, {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {}
    });
    return res.json(data);
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

router.delete("/api/resumes/:resumeId", requireAuth, async (req, res) => {
  const { resumeId } = req.params;
  const token = getAuthToken(req);

  try {
    const { data } = await apiClient.delete(`/resumes/${resumeId}`, {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {}
    });
    return res.json(data);
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

router.post("/api/judge-batch/:jobId", requireAuth, async (req, res) => {
  const { jobId } = req.params;
  const { threshold = 70 } = req.body;
  const token = getAuthToken(req);

  try {
    const { data } = await apiClient.post(`/judge-batch/${jobId}?threshold=${threshold}`, {}, {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {}
    });
    return res.json(data);
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

router.get("/resume/:resumeId", requireAuth, async (req, res) => {
  const { resumeId } = req.params;
  const token = getAuthToken(req);

  try {
    const response = await apiClient.get(`/resume/${resumeId}`, {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {},
      responseType: 'arraybuffer'
    });
    
    const contentType = response.headers['content-type'] || 'application/pdf';
    res.set('Content-Type', contentType);
    res.set('Content-Disposition', 'inline');
    return res.send(Buffer.from(response.data));
  } catch (error) {
    console.error("Error proxying resume:", error.response?.data ? error.response.data.toString() : error.message);
    const status = error.response?.status || 404;
    return res.status(status).send(error.response?.data ? error.response.data.toString() : "Resume file not found");
  }
});

module.exports = { dashboardRouter: router };
