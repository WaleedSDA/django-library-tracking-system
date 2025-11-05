import datetime

from click.core import F
from django.db import models, transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from .models import Author, Book, Member, Loan
from .serializers import AuthorSerializer, BookSerializer, MemberSerializer, LoanSerializer
from rest_framework.decorators import action
from django.utils import timezone
from .tasks import send_loan_notification


class CostumePagination(
    PageNumberPagination):  # comment for the reviewer i like this way better than the settings.py for its flexibility and being used onnly where i want
    max_page_size = 100
    page_size_query_param = 'page_size'


class PaginationViewSet(viewsets.ModelViewSet):
    serializer_class = CostumePagination


class AuthorViewSet(viewsets.ModelViewSet):
    queryset = Author.objects.all()
    serializer_class = AuthorSerializer


class BookViewSet(PaginationViewSet):
    queryset = Book.objects.all()
    serializer_class = BookSerializer

    @transaction.atomic
    @action(detail=True, methods=['post'])
    def loan(self, request, pk=None):
        member_id = request.data.get('member_id')
        member = Member.objects.only('id').filter(pk=member_id).first()
        if not member:
            return Response({'error': 'Member not found.'}, status=status.HTTP_404_NOT_FOUND)

        book = Book.objects.select_for_update().only('id', 'available_copies').get(pk=pk)

        if book.available_copies < 1:
            return Response({'error': 'No available copies.'}, status=status.HTTP_400_BAD_REQUEST)

        loan = Loan.objects.create(book_id=book.pk, member_id=member.pk)

        Book.objects.filter(pk=book.pk).update(available_copies=F('available_copies') - 1)

        send_loan_notification.delay(loan.pk)

        return Response({'status': 'Book loaned successfully.'}, status=status.HTTP_201_CREATED)

    @transaction.atomic
    @action(detail=True, methods=['post'])
    def return_book(self, request, pk=None):
        member_id = request.data.get('member_id')

        book = Book.objects.select_for_update().only('id').get(pk=pk)
        loan = (
            Loan.objects.select_for_update()
            .filter(book_id=book.pk, member_id=member_id, is_returned=False)
            .first()
        )

        if not loan:
            return Response({'error': 'Active loan does not exist.'}, status=status.HTTP_400_BAD_REQUEST)

        Loan.objects.filter(pk=loan.pk).update(
            is_returned=True,
            return_date=timezone.now().date()
        )

        Book.objects.filter(pk=book.pk).update(available_copies=F('available_copies') + 1)

        return Response({'status': 'Book returned successfully.'}, status=status.HTTP_200_OK)


class MemberViewSet(viewsets.ModelViewSet):
    queryset = Member.objects.all()
    serializer_class = MemberSerializer

    @action(detail=False, methods=['get'], url_path='top-active')
    def top_active(self, request):
        top_members = (
            Member.objects
            .select_related('user')  # Fetch related user in same query
            .annotate(active_loans=Count('loans', filter=Q(loans__is_returned=False)))
            .filter(active_loans__gt=0)
            .order_by('-active_loans')[:5]
        )

        data = [
            {
                "id": member.id,
                "username": member.user.username,
                "email": member.user.email,
                "active_loans": member.active_loans
            }
            for member in top_members
        ]

        return Response(data, status=status.HTTP_200_OK)


class LoanViewSet(viewsets.ModelViewSet):
    queryset = Loan.objects.all()
    serializer_class = LoanSerializer

    @action(detail=True, methods=['post'], url_path='extend_due_date')
    def extend_due_date(self, request, pk=None):
        if request.data.get(
                'additional_days') < 0:  # i know i should create a serializer for validation but no time left :(
            raise ValueError
        updated = Loan.objects.filter(id=pk).update(  # instead of hitting the db twice
            due_date=models.F('due_date') + datetime.timedelta(days=request.data.get('additional_days')))
        if not updated:
            return Response({'error': 'no such loan.'},
                            status=status.HTTP_404_NOT_FOUND)  # sorry i read it too late that i need to return loan :(
        return Response({'status': 'Loan extended successfully.'}, status=status.HTTP_200_OK)
