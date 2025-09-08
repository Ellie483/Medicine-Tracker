// Main JavaScript for Medicine Availability Tracker

document.addEventListener('DOMContentLoaded', function() {
    // Initialize tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // Auto-hide alerts after 5 seconds
    setTimeout(function() {
        var alerts = document.querySelectorAll('.alert');
        alerts.forEach(function(alert) {
            var bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        });
    }, 5000);

    // Add fade-in animation to cards
    var cards = document.querySelectorAll('.card');
    cards.forEach(function(card, index) {
        card.style.animationDelay = (index * 0.1) + 's';
        card.classList.add('fade-in');
    });

    // Form validation
    var forms = document.querySelectorAll('.needs-validation');
    forms.forEach(function(form) {
        form.addEventListener('submit', function(event) {
            if (!form.checkValidity()) {
                event.preventDefault();
                event.stopPropagation();
            }
            form.classList.add('was-validated');
        });
    });

    // Medicine search functionality
    initializeMedicineSearch();
    
    // Initialize dashboard features
    initializeDashboard();
});

function initializeMedicineSearch() {
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.addEventListener('input', debounce(function() {
            const searchTerm = this.value.toLowerCase();
            filterMedicines(searchTerm);
        }, 300));
    }
}

function filterMedicines(searchTerm) {
    const medicineCards = document.querySelectorAll('.medicine-card');
    let visibleCount = 0;

    medicineCards.forEach(function(card) {
        const medicineName = card.querySelector('.card-title').textContent.toLowerCase();
        const medicineDescription = card.querySelector('.card-text') ? 
            card.querySelector('.card-text').textContent.toLowerCase() : '';
        
        if (medicineName.includes(searchTerm) || medicineDescription.includes(searchTerm)) {
            card.parentElement.style.display = 'block';
            card.classList.add('slide-in');
            visibleCount++;
        } else {
            card.parentElement.style.display = 'none';
        }
    });

    // Show no results message if needed
    updateSearchResults(visibleCount, searchTerm);
}

function updateSearchResults(count, searchTerm) {
    let noResultsMsg = document.getElementById('noResultsMessage');
    
    if (count === 0 && searchTerm) {
        if (!noResultsMsg) {
            noResultsMsg = document.createElement('div');
            noResultsMsg.id = 'noResultsMessage';
            noResultsMsg.className = 'text-center py-4';
            noResultsMsg.innerHTML = `
                <i class="fas fa-search fa-3x text-muted mb-3"></i>
                <h5>No medicines found</h5>
                <p class="text-muted">Try searching with different keywords.</p>
            `;
            document.getElementById('medicineGrid').appendChild(noResultsMsg);
        }
        noResultsMsg.style.display = 'block';
    } else if (noResultsMsg) {
        noResultsMsg.style.display = 'none';
    }
}

function initializeDashboard() {
    // Add click handlers for dashboard cards
    const dashboardCards = document.querySelectorAll('.dashboard-card');
    dashboardCards.forEach(function(card) {
        card.style.cursor = 'pointer';
        card.addEventListener('click', function() {
            this.style.transform = 'scale(0.98)';
            setTimeout(() => {
                this.style.transform = 'scale(1)';
            }, 150);
        });
    });

    // Initialize stock level indicators
    updateStockIndicators();
    
    // Initialize order status updates
    initializeOrderTracking();
}

function updateStockIndicators() {
    const stockBadges = document.querySelectorAll('.stock-badge');
    stockBadges.forEach(function(badge) {
        const stock = parseInt(badge.textContent);
        if (stock <= 10) {
            badge.classList.remove('bg-success', 'bg-warning');
            badge.classList.add('bg-danger');
        } else if (stock <= 50) {
            badge.classList.remove('bg-success', 'bg-danger');
            badge.classList.add('bg-warning');
        } else {
            badge.classList.remove('bg-warning', 'bg-danger');
            badge.classList.add('bg-success');
        }
    });
}

function initializeOrderTracking() {
    // Simulate real-time order status updates
    const orderStatusBadges = document.querySelectorAll('.order-status');
    orderStatusBadges.forEach(function(badge) {
        // Add pulse animation for pending orders
        if (badge.textContent.toLowerCase().includes('pending')) {
            badge.style.animation = 'pulse 2s infinite';
        }
    });
}

// Utility functions
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
    notification.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
    notification.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    document.body.appendChild(notification);
    
    // Auto remove after 5 seconds
    setTimeout(() => {
        if (notification.parentNode) {
            notification.parentNode.removeChild(notification);
        }
    }, 5000);
}

function formatCurrency(amount) {
    return  parseFloat(amount).toFixed(2)+ 'Ks' ;
}

function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-IN', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
    });
}

// Add to cart functionality
function addToCart(medicineId, quantity = 1) {
    const formData = new FormData();
    formData.append('medicine_id', medicineId);
    formData.append('quantity', quantity);
    
    fetch('/buyer/add_to_cart', {
        method: 'POST',
        body: formData
    })
    .then(response => {
        if (response.ok) {
            showNotification('Medicine added to cart successfully!', 'success');
            // Redirect to checkout or update cart UI
            setTimeout(() => {
                window.location.reload();
            }, 1000);
        } else {
            showNotification('Failed to add medicine to cart.', 'danger');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('An error occurred. Please try again.', 'danger');
    });
}

// Medicine management for sellers
function deleteMedicine(medicineId) {
    if (confirm('Are you sure you want to delete this medicine?')) {
        // In a real application, this would make an API call
        showNotification('Medicine deleted successfully!', 'success');
        // Remove the row from the table
        const row = document.querySelector(`[data-medicine-id="${medicineId}"]`);
        if (row) {
            row.remove();
        }
    }
}

function editMedicine(medicineId) {
    // In a real application, this would open an edit modal or redirect to edit page
    showNotification('Edit functionality would be implemented here.', 'info');
}

// QR Code functionality
function generateQRCode(data) {
    // This would typically use a QR code library
    console.log('Generating QR code for:', data);
}

// Map functionality (placeholder)
function initializeMap() {
    // This would integrate with Google Maps or similar service
    console.log('Map initialization would be implemented here.');
}

// File upload handling
function handleFileUpload(input) {
    const file = input.files[0];
    if (file) {
        const maxSize = 5 * 1024 * 1024; // 5MB
        if (file.size > maxSize) {
            showNotification('File size should not exceed 5MB.', 'warning');
            input.value = '';
            return;
        }
        
        const allowedTypes = ['image/jpeg', 'image/png', 'image/gif', 'application/pdf'];
        if (!allowedTypes.includes(file.type)) {
            showNotification('Please upload only images (JPEG, PNG, GIF) or PDF files.', 'warning');
            input.value = '';
            return;
        }
        
        showNotification('File selected successfully!', 'success');
    }
}

// Form submission with loading state
function submitFormWithLoading(form) {
    const submitBtn = form.querySelector('button[type="submit"]');
    const originalText = submitBtn.innerHTML;
    
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Processing...';
    
    // Re-enable button after form submission (in case of errors)
    setTimeout(() => {
        submitBtn.disabled = false;
        submitBtn.innerHTML = originalText;
    }, 3000);
}

// Add event listeners for forms
document.addEventListener('submit', function(e) {
    const form = e.target;
    if (form.tagName === 'FORM') {
        submitFormWithLoading(form);
    }
});

// Keyboard shortcuts
document.addEventListener('keydown', function(e) {
    // Ctrl/Cmd + K for search
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        const searchInput = document.getElementById('searchInput');
        if (searchInput) {
            searchInput.focus();
        }
    }
    
    // Escape to clear search
    if (e.key === 'Escape') {
        const searchInput = document.getElementById('searchInput');
        if (searchInput && searchInput.value) {
            searchInput.value = '';
            filterMedicines('');
        }
    }
});
