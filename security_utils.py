# security_utils.py - Utility functions untuk keamanan
import hashlib
import secrets
import re
from typing import List

class SecurityUtils:
    """
    Utility functions untuk validasi dan keamanan
    """
    
    @staticmethod
    def validate_password_strength(password: str) -> tuple[bool, List[str]]:
        """
        Validasi strength password dengan feedback
        """
        errors = []
        
        if len(password) < 8:
            errors.append("Password minimal 8 karakter")
        
        if len(password) > 128:
            errors.append("Password maksimal 128 karakter")
        
        if not re.search(r'[A-Z]', password):
            errors.append("Password harus mengandung minimal 1 huruf besar")
        
        if not re.search(r'[a-z]', password):
            errors.append("Password harus mengandung minimal 1 huruf kecil")
        
        if not re.search(r'\d', password):
            errors.append("Password harus mengandung minimal 1 angka")
        
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            errors.append("Password harus mengandung minimal 1 karakter khusus")
        
        # Check for common patterns
        common_patterns = [
            r'123456', r'password', r'admin', r'qwerty',
            r'letmein', r'welcome', r'monkey', r'dragon'
        ]
        
        for pattern in common_patterns:
            if re.search(pattern, password.lower()):
                errors.append("Password terlalu umum, gunakan kombinasi yang lebih unik")
                break
        
        return len(errors) == 0, errors

    @staticmethod
    def generate_secure_token(length: int = 32) -> str:
        """Generate secure random token"""
        return secrets.token_urlsafe(length)

    @staticmethod
    def hash_data(data: str, salt: str = None) -> str:
        """Hash data dengan salt"""
        if salt is None:
            salt = secrets.token_hex(16)
        
        hash_input = f"{data}{salt}".encode('utf-8')
        return hashlib.sha256(hash_input).hexdigest()

    @staticmethod
    def validate_username(username: str) -> tuple[bool, str]:
        """Validate username format"""
        if len(username) < 3:
            return False, "Username minimal 3 karakter"
        
        if len(username) > 50:
            return False, "Username maksimal 50 karakter"
        
        if not re.match(r'^[a-zA-Z0-9_.-]+$', username):
            return False, "Username hanya boleh mengandung huruf, angka, underscore, titik, dan dash"
        
        if username.lower() in ['admin', 'root', 'administrator', 'system', 'koronka']:
            return False, "Username tidak diperbolehkan"
        
        return True, ""

    @staticmethod
    def sanitize_input(input_str: str) -> str:
        """Sanitize user input"""
        if not isinstance(input_str, str):
            return ""
        
        # Remove potential XSS characters
        dangerous_chars = ['<', '>', '"', "'", '&', '\\']
        for char in dangerous_chars:
            input_str = input_str.replace(char, '')
        
        return input_str.strip()