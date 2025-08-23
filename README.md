# 💊 Medicine Availability Tracker

A complete responsive full-stack web application for tracking medicine availability across pharmacies with role-based access control.

## 🚀 Features

### 👥 Three User Roles:

#### Admin
- **Credentials**: `admin` / `admin`
- View all registered users (sellers and buyers)
- Remove users and moderate listings
- Dashboard with system statistics

#### Seller (Pharmacy)
- **Credentials**: `seller` / `seller`
- Complete pharmacy registration with license details
- Add, edit, and manage medicine inventory
- View order history and low stock alerts
- Upload purchase receipts

#### Buyer (User)
- **Credentials**: `buyer` / `buyer`
- Search medicines by name across all pharmacies
- View nearby pharmacies and their details
- Add medicines to cart and checkout with QR code payment
- Upload receipts and track order history

## 🛠️ Tech Stack

- **Backend**: FastAPI (Python)
- **Frontend**: HTML5, CSS3, Bootstrap 5, JavaScript
- **Database**: MongoDB with Motor (async driver)
- **Authentication**: JWT-based with role-based access control
- **Template Engine**: Jinja2
- **Additional**: QR Code generation, File uploads

## 📦 Installation

1. **Clone or navigate to the project directory**
   ```bash
   cd c:\Users\User\CascadeProjects\medicine
   ```

2. **Install Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up MongoDB**
   - Install MongoDB locally or use MongoDB Atlas
   - Update the `.env` file with your MongoDB connection string

4. **Configure environment variables**
   - Copy `.env` file and update the values:
   ```
   MONGODB_URL=mongodb://localhost:27017
   DATABASE_NAME=medicine_tracker
   SECRET_KEY=your-secret-key-here-change-in-production
   ```

5. **Run the application**
   ```bash
   python main.py
   ```
   
   Or using uvicorn directly:
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   ```

6. **Access the application**
   - Open your browser and go to: `http://localhost:8000`

## 🧪 Test Accounts

| Role | Username | Password | Description |
|------|----------|----------|-------------|
| Admin | `admin` | `admin` | Full system access |
| Seller | `seller` | `seller` | Pharmacy management |
| Buyer | `buyer` | `buyer` | Medicine search & purchase |

## 📁 Project Structure

```
medicine/
├── main.py                 # FastAPI application entry point
├── models.py              # Pydantic models and MongoDB schemas
├── database.py            # MongoDB connection and configuration
├── auth.py                # Authentication and authorization logic
├── utils.py               # Utility functions (QR codes, distance calc)
├── requirements.txt       # Python dependencies
├── .env                   # Environment variables
├── README.md             # Project documentation
├── templates/            # Jinja2 HTML templates
│   ├── base.html
│   ├── login.html
│   ├── admin_dashboard.html
│   ├── seller_profile.html
│   ├── seller_dashboard.html
│   ├── add_medicine.html
│   ├── buyer_profile.html
│   ├── buyer_dashboard.html
│   └── checkout.html
└── static/              # Static assets
    ├── css/
    │   └── style.css    # Custom styles
    ├── js/
    │   └── main.js      # JavaScript functionality
    ├── qr_codes/        # Generated QR codes
    └── uploads/         # Uploaded files
```

## 🔐 Authentication Flow

1. **Login Page**: Users enter credentials
2. **Role Detection**: System identifies user role (admin/seller/buyer)
3. **Profile Check**: 
   - If profile incomplete → Redirect to profile setup
   - If complete → Redirect to role-specific dashboard
4. **Session Management**: JWT tokens with role-based access control

## 💾 Database Collections

- **users**: User credentials and roles
- **pharmacy_profiles**: Seller pharmacy information
- **buyer_profiles**: Buyer personal information
- **medicines**: Medicine inventory with stock and pricing
- **orders**: Purchase orders and transaction history
- **receipts**: Uploaded receipt files

## 🎨 UI Features

- **Responsive Design**: Works on desktop and mobile devices
- **Modern UI**: Bootstrap 5 with custom styling
- **Interactive Elements**: Search, filtering, and real-time updates
- **QR Code Generation**: For payment processing
- **File Upload Support**: For receipts and documents
- **Role-based Navigation**: Different interfaces for each user type

## 🔧 API Endpoints

### Authentication
- `POST /login` - User login
- `GET /logout` - User logout

### Admin Routes
- `GET /admin/dashboard` - Admin dashboard
- `POST /admin/remove_user/{user_id}` - Remove user

### Seller Routes
- `GET /seller/profile` - Pharmacy registration form
- `POST /seller/profile` - Create pharmacy profile
- `GET /seller/dashboard` - Seller dashboard
- `GET /seller/add_medicine` - Add medicine form
- `POST /seller/add_medicine` - Create new medicine

### Buyer Routes
- `GET /buyer/profile` - Buyer profile form
- `POST /buyer/profile` - Create buyer profile
- `GET /buyer/dashboard` - Buyer dashboard
- `POST /buyer/search_medicines` - Search medicines
- `POST /buyer/add_to_cart` - Add medicine to cart
- `GET /buyer/checkout/{order_id}` - Checkout page
- `POST /buyer/confirm_payment/{order_id}` - Confirm payment

## 🚀 Deployment

The application is ready for deployment on platforms like:
- **Heroku**: Add Procfile and configure MongoDB Atlas
- **AWS**: Use EC2 with MongoDB Atlas or DocumentDB
- **Docker**: Create Dockerfile for containerization
- **Vercel/Netlify**: For static frontend with serverless backend

## 🔒 Security Features

- Password hashing with bcrypt
- JWT token-based authentication
- Role-based access control
- Input validation and sanitization
- File upload restrictions
- CORS protection

## 📱 Mobile Responsiveness

- Bootstrap 5 responsive grid system
- Mobile-optimized forms and navigation
- Touch-friendly buttons and interactions
- Responsive tables and cards

## 🎯 Future Enhancements

- Real-time notifications with WebSockets
- Google Maps integration for pharmacy locations
- SMS/Email notifications for low stock
- Advanced search filters and sorting
- Inventory analytics and reporting
- Multi-language support
- Payment gateway integration
- Mobile app development

## 🐛 Troubleshooting

### Common Issues:

1. **MongoDB Connection Error**
   - Ensure MongoDB is running
   - Check connection string in `.env`

2. **Module Import Errors**
   - Install all dependencies: `pip install -r requirements.txt`

3. **Port Already in Use**
   - Change port in `main.py` or kill existing process

4. **Static Files Not Loading**
   - Check file paths in templates
   - Ensure static directory structure is correct

## 📞 Support

For issues or questions:
1. Check the troubleshooting section
2. Review the code comments and documentation
3. Ensure all dependencies are properly installed
4. Verify MongoDB connection and configuration

## 📄 License

This project is created for educational and demonstration purposes.
