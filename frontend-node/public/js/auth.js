/**
 * Frontend authentication service
 * Handles JWT token storage, session management, and API calls
 */

const AUTH_TOKEN_KEY = 'auth_token';
const USER_ID_KEY = 'user_id';
const USER_NAME_KEY = 'user_name';
const USER_EMAIL_KEY = 'user_email';
const PROFILE_KEY = 'user_profile';

class AuthService {
  constructor(apiBase) {
    this.apiBase = apiBase || 'http://localhost:8000';
  }

  /**
   * Get stored JWT token
   */
  getToken() {
    return localStorage.getItem(AUTH_TOKEN_KEY);
  }

  /**
   * Get current user ID
   */
  getUserId() {
    return localStorage.getItem(USER_ID_KEY);
  }

  /**
   * Get current user info
   */
  getCurrentUser() {
    return {
      user_id: localStorage.getItem(USER_ID_KEY),
      name: localStorage.getItem(USER_NAME_KEY),
      email: localStorage.getItem(USER_EMAIL_KEY),
    };
  }

  /**
   * Check if user is authenticated
   */
  isAuthenticated() {
    return !!this.getToken();
  }

  /**
   * Verify token with backend
   */
  async verifyToken() {
    try {
      const response = await fetch(`${this.apiBase}/auth/verify-token`, {
        headers: {
          'Authorization': `Bearer ${this.getToken()}`,
        },
      });

      if (response.status === 401) {
        this.logout();
        return false;
      }

      return response.ok;
    } catch (error) {
      console.error('Error verifying token:', error);
      return false;
    }
  }

  /**
   * Fetch user profile
   */
  async fetchProfile() {
    try {
      const response = await fetch(`${this.apiBase}/auth/profile`, {
        headers: {
          'Authorization': `Bearer ${this.getToken()}`,
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error('Failed to fetch profile');
      }

      const profile = await response.json();
      localStorage.setItem(PROFILE_KEY, JSON.stringify(profile));
      return profile;
    } catch (error) {
      console.error('Error fetching profile:', error);
      return null;
    }
  }

  /**
   * Get cached profile
   */
  getCachedProfile() {
    const profile = localStorage.getItem(PROFILE_KEY);
    return profile ? JSON.parse(profile) : null;
  }

  /**
   * Get Gmail connection URL
   */
  async getGmailConnectUrl() {
    try {
      const response = await fetch(`${this.apiBase}/auth/google/gmail-connect-url`, {
        headers: {
          'Authorization': `Bearer ${this.getToken()}`,
        },
      });

      if (!response.ok) {
        throw new Error('Failed to get Gmail connect URL');
      }

      const data = await response.json();
      return data.oauth_url;
    } catch (error) {
      console.error('Error getting Gmail connect URL:', error);
      return null;
    }
  }

  /**
   * Disconnect Gmail account
   */
  async disconnectGmail(gmailEmail) {
    try {
      const response = await fetch(`${this.apiBase}/auth/gmail/disconnect/${gmailEmail}`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${this.getToken()}`,
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error('Failed to disconnect Gmail');
      }

      // Refresh profile
      await this.fetchProfile();
      return true;
    } catch (error) {
      console.error('Error disconnecting Gmail:', error);
      return false;
    }
  }

  /**
   * Set active Gmail account
   */
  async setActiveGmail(gmailEmail) {
    try {
      const response = await fetch(`${this.apiBase}/auth/gmail/set-active/${gmailEmail}`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${this.getToken()}`,
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error('Failed to set active Gmail');
      }

      // Refresh profile
      await this.fetchProfile();
      return true;
    } catch (error) {
      console.error('Error setting active Gmail:', error);
      return false;
    }
  }

  /**
   * Logout user
   */
  logout() {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(USER_ID_KEY);
    localStorage.removeItem(USER_NAME_KEY);
    localStorage.removeItem(USER_EMAIL_KEY);
    localStorage.removeItem(PROFILE_KEY);
    window.location.href = '/login';
  }

  /**
   * Make authenticated API call
   */
  async fetchWithAuth(endpoint, options = {}) {
    const headers = {
      'Authorization': `Bearer ${this.getToken()}`,
      'Content-Type': 'application/json',
      ...options.headers,
    };

    try {
      const response = await fetch(endpoint, {
        ...options,
        headers,
      });

      if (response.status === 401) {
        this.logout();
        throw new Error('Unauthorized - session expired');
      }

      return response;
    } catch (error) {
      console.error('API call error:', error);
      throw error;
    }
  }
}

// Export for use in other modules
window.AuthService = AuthService;
