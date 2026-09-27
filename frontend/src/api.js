export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}
export async function request(
  path,
  { token, body, method = "GET", blob = false } = {},
) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (
    body &&
    !(body instanceof FormData) &&
    !(body instanceof URLSearchParams)
  ) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(`/api/v1/${path}`, { method, headers, body });
  } catch {
    throw new ApiError("Connection failed. Please try again.", 0);
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail =
      typeof data.detail === "string"
        ? data.detail
        : "The request could not be completed. Check your input and try again.";
    throw new ApiError(detail, response.status);
  }
  if (response.status === 204) return null;
  return blob ? response.blob() : response.json();
}
