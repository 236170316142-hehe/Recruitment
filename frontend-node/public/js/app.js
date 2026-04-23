// ============================================================================
// AUTHENTICATION SETUP
// ============================================================================

const BACKEND_API_BASE = window.location.hostname === 'localhost'
  ? 'http://localhost:8000'
  : window.location.origin.replace(':3000', ':8000');

let authService = null;

// ============================================================================
// CLIENT-SIDE APPLICATION HELPER FUNCTIONS
// ============================================================================

/**
 * Fetch helper with error handling
 */
async function fetchAPI(endpoint, options = {}) {
  try {
    const response = await fetch(endpoint, {
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
      ...options,
    });

    if (!response.ok) {
      throw new Error(`API Error: ${response.statusText}`);
    }

    return await response.json();
  } catch (error) {
    console.error("Fetch error:", error);
    throw error;
  }
}

/**
 * Format date/time
 */
function formatDate(dateString) {
  const date = new Date(dateString);
  return date.toLocaleDateString() + " " + date.toLocaleTimeString();
}

/**
 * Show notification
 */
function showNotification(message, type = "info") {
  console.log(`[${type.toUpperCase()}] ${message}`);
  // Can be enhanced with UI notification element
}

/**
 * Hide upload status after delay
 */
function hideUploadStatusAfterDelay(elementId, delay = 5000) {
  setTimeout(() => {
    const element = document.getElementById(elementId);
    if (element) {
      element.style.display = "none";
    }
  }, delay);
}

// ============================================================================
// AUTHENTICATION FUNCTIONS
// ============================================================================

function ensureAuthenticated() {
  if (!authService.isAuthenticated()) {
    window.location.href = '/login';
  }
}

function toggleProfileDropdown() {
  const dropdown = document.getElementById('profileDropdown');
  if (dropdown) {
    dropdown.classList.toggle('open');
  }
}

function closeProfileDropdown() {
  const dropdown = document.getElementById('profileDropdown');
  if (dropdown) {
    dropdown.classList.remove('open');
  }
}

async function openGmailSettings(event) {
  event.preventDefault();
  closeProfileDropdown();
  const modal = document.getElementById('gmailModal');
  if (modal) {
    modal.style.display = 'block';
  }
}

async function connectGmailAccount() {
  try {
    const url = await authService.getGmailConnectUrl();
    if (url) {
      window.location.href = url;
    } else {
      alert('Failed to get Gmail connection URL');
    }
  } catch (error) {
    console.error('Error connecting Gmail:', error);
    alert('Failed to connect Gmail account');
  }
}

function handleLogout(event) {
  event.preventDefault();
  authService.logout();
}

// Close dropdown when clicking outside
document.addEventListener('click', function(event) {
  const dropdown = document.getElementById('profileDropdown');
  const profileBtn = document.querySelector('.user-profile-button');
  if (dropdown && profileBtn && !profileBtn.contains(event.target) && !dropdown.contains(event.target)) {
    closeProfileDropdown();
  }
});

// ============================================================================
// PAGE-SPECIFIC INITIALIZATION
// ============================================================================

document.addEventListener("DOMContentLoaded", () => {
  // Initialize auth service
  authService = new AuthService(BACKEND_API_BASE);

  // Check authentication (skip for login page)
  if (window.location.pathname !== '/login' && !authService.isAuthenticated()) {
    window.location.href = '/login';
    return;
  }

  // Setup drag and drop handlers
  setupDragDropZones();

  // Setup modal close handlers
  setupModals();
});

function setupDragDropZones() {
  const zones = document.querySelectorAll(".drag-drop-zone");
  zones.forEach((zone) => {
    zone.addEventListener("dragover", (e) => {
      e.preventDefault();
      zone.classList.add("drag-active");
    });

    zone.addEventListener("dragleave", () => {
      zone.classList.remove("drag-active");
    });

    zone.addEventListener("drop", (e) => {
      e.preventDefault();
      zone.classList.remove("drag-active");
      const fileInput = zone.querySelector("input[type='file']");
      if (fileInput) {
        fileInput.files = e.dataTransfer.files;
        updateFileList(fileInput);
      }
    });
  });
}

function updateFileList(fileInput) {
  const container = fileInput.closest("form") || fileInput.parentElement;
  let fileList = container.querySelector(".file-list");

  if (!fileList) {
    fileList = document.createElement("div");
    fileList.className = "file-list";
    fileInput.parentElement.insertAdjacentElement("afterend", fileList);
  }

  fileList.innerHTML = "";
  for (let file of fileInput.files) {
    const item = document.createElement("div");
    item.className = "file-item";
    item.textContent = `✓ ${file.name}`;
    fileList.appendChild(item);
  }
}

function setupModals() {
  const modals = document.querySelectorAll('.modal');
  modals.forEach(modal => {
    const closeBtn = modal.querySelector('.close');
    if (closeBtn) {
      closeBtn.onclick = () => {
        modal.style.display = 'none';
      };
    }

    window.onclick = (event) => {
      if (event.target === modal) {
        modal.style.display = 'none';
      }
    };
  });
}
