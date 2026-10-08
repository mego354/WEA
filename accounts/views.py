from django.shortcuts import render, redirect
from django.db import models
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import User, Role


def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        
        # In custom User, email can match email or username
        user = authenticate(request, username=email, password=password)
        if not user:
            # Check by email lookup
            user_obj = User.objects.filter(email__iexact=email).first()
            if user_obj:
                user = authenticate(request, username=user_obj.username, password=password)

        if user:
            login(request, user)
            messages.success(request, f"مرحباً بك مجدداً د. {user.name or user.username}")
            next_url = request.GET.get('next') or request.POST.get('next') or 'home'
            return redirect(next_url)
        else:
            messages.error(request, "البريد الإلكتروني أو كلمة المرور غير صحيحة.")

    return render(request, 'accounts/login.html')


def logout_view(request):
    logout(request)
    messages.info(request, "تم تسجيل الخروج بنجاح.")
    return redirect('login')


@login_required
def users_list(request):
    users = User.objects.select_related('role').order_by('-created_at')
    return render(request, 'accounts/users_list.html', {'users': users})


@login_required
def roles_list(request):
    roles = Role.objects.annotate(users_count=models.Count('users')).order_by('id')
    return render(request, 'accounts/roles_list.html', {'roles': roles})
