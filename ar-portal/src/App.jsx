import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import VendorUploadPage from './pages/VendorUploadPage'
import VendorComparePage from './pages/VendorComparePage'
import VendorConfirmPage from './pages/VendorConfirmPage'
import CustomerUploadPage from './pages/CustomerUploadPage'
import CustomerReviewPage from './pages/CustomerReviewPage'
import CustomerConfirmPage from './pages/CustomerConfirmPage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/"                    element={<LoginPage />} />
        <Route path="/dashboard"           element={<DashboardPage />} />
        <Route path="/vendor/upload"       element={<VendorUploadPage />} />
        <Route path="/vendor/compare"      element={<VendorComparePage />} />
        <Route path="/vendor/confirm"      element={<VendorConfirmPage />} />
        <Route path="/customer/upload"     element={<CustomerUploadPage />} />
        <Route path="/customer/review"     element={<CustomerReviewPage />} />
        <Route path="/customer/confirm"    element={<CustomerConfirmPage />} />
        <Route path="*"                    element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
