// Edit after deploying. Never put an API key here; the browser only talks to your API.
window.APP_CONFIG = {
  LEVEL: 1,                                   // 1,2 anonymous | 3,4,5,6,7 need Cognito login
  API_URL: "https://YOUR_API_ID.execute-api.REGION.amazonaws.com",   // or "/api" behind CloudFront
  COGNITO_DOMAIN: "https://YOUR_PREFIX.auth.REGION.amazoncognito.com", // levels 3-7
  COGNITO_CLIENT_ID: "YOUR_APP_CLIENT_ID",                              // levels 3-7
  REDIRECT_URI: window.location.origin + window.location.pathname
};
