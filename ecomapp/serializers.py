from rest_framework import serializers
from .models import CustomUser,Product,ProductImage,Order,OrderItem,Category,Cart,CartItem,Company,OrderCompanyStatus
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db import transaction

class CompanySerializer(serializers.ModelSerializer):
    
    
    class Meta:
        model=Company
        fields = [ 'name' ]  


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    Confirm_Password = serializers.CharField(write_only=True)
    company = CompanySerializer(required=False, allow_null=True)

    class Meta:
        model = CustomUser
        fields = ['id', 'first_name', 'last_name', 'username', 'role', 'email', 'password', 'Confirm_Password', 'company']

    def validate(self, data):
        if data.get('password') != data.get('Confirm_Password'):
            raise serializers.ValidationError("Passwords do not match")
        return data

    def create(self, validated_data):
        company_data = validated_data.pop('company', None)
        validated_data.pop('Confirm_Password', None)
        password = validated_data.pop('password')

        user = CustomUser(**validated_data)

        # Validate the password
        try:
            validate_password(password=password, user=user)
        except ValidationError as err:
            raise serializers.ValidationError({'password': err.messages})

        # Set and encrypt the password
        user.set_password(password)
        user.save()

        if company_data:
            company_name = company_data.get('name')
            if company_name:
                # Create or get the company and set the owner_id
                company, created = Company.objects.get_or_create(name=company_name, defaults={'owner_id': user.id})
                # Assign the created or existing company to the user
                user.company_user = company
                user.save()

        return user

    def update(self, instance, validated_data):
        company_data = validated_data.pop('company', None)
        password = validated_data.pop('password', None)
        user = super().update(instance, validated_data)
        
        if password:
            user.set_password(password)
            user.save()

        if company_data:
            company_name = company_data.get('name')
            if company_name:
                # Create or get the company and set the owner_id
                company, created = Company.objects.get_or_create(name=company_name, defaults={'owner_id': user.id})
                # Assign the created or existing company to the user
                user.company_user = company
                user.save()

        return user

class UserLoginSerializer(serializers. ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ['email','password']


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model=Category
        fields = '__all__'
        

# class ShopSerializer(serializers.ModelSerializer):
#     class Meta:
#         model=Shop
#         fields = '__all__'

class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ['id', 'image']

class ProductSerializer(serializers.ModelSerializer):
    
    category_id = serializers.IntegerField(write_only=True)
    images = ProductImageSerializer(many=True, required=False, read_only =True)
    uploaded_images = serializers. ListField(
    child=serializers. ImageField(max_length = 1000000, allow_empty_file = False, use_url = False),
    write_only=True)
    discounted_price = serializers.FloatField(source='get_discounted_price', read_only=True)
    class Meta:
        model = Product
        fields = ['id','company' ,'category_id','Product_name', 'Quantity', 'discount','price','discounted_price', 'Description', 'images','uploaded_images' ]

    def create(self, validated_data):
        
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            if request.user.role == 'staff':
                validated_data['company'] = request.user.company_user

        category_id = validated_data.pop('category_id')
        # shop_id =validated_data.pop('shop_id')
        uploaded_images = validated_data.pop('uploaded_images', [])

        # Fetch the category instance
        category = Category.objects.get(id=category_id)
        
        product = Product.objects.create(category=category, **validated_data)

        # Create ProductImage instances
        ProductImage.objects.bulk_create([
            ProductImage(product=product, image=image) for image in uploaded_images
        ])
       

        return product
    
#------------------ListSerializer-------------------------making new changes.....
class CustomOrderItemListSerializer(serializers.ListSerializer):
    # def validate(self, attrs):
    #     print("Self--------",self)
    #     print("Attrs--------",attrs)
    #     order=self.context.get('order')
    #     print("Order--------",order)
    #     for item in attrs:
    #         item['order'] = order   #order_id needed instead of self.instance.
    #     return super().validate(attrs)
    
    

    def update(self, instance, validated_data):
        
        instance_mapping = {item.id: item for item in instance}
        ret = []
        

        for data in validated_data:
            item_id = data.get('id')
            
            if item_id and item_id in instance_mapping:
                # Update existing instance
                ret.append(self.child.update(instance_mapping.pop(item_id), data))
            else:
                # Create new instance
                data['order'] = instance[0].order
                ret.append(self.child.create(data))

        if instance_mapping:
            ids_to_delete = instance_mapping.keys()
            OrderItem.objects.filter(id__in=ids_to_delete).delete()
        return ret
    


#-------------------------------------------------------------------------------

class OrderItemSerializer(serializers.ModelSerializer):
    # id = serializers.IntegerField(required=False)
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())

    class Meta:
        model = OrderItem
        fields = ['id', 'product', 'quantity']
        list_serializer_class = CustomOrderItemListSerializer

  

    
    
        

class UserOrderSerializer(serializers.ModelSerializer):
    order_items = OrderItemSerializer(many=True)
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())
    
    class Meta:
        model = Order
        fields = ['id', 'user', 'order_items', 'location', 'time_of_delivery', 'date_ordered', 'date_ordered', 'total_price']
        read_only_fields = ['date_ordered', 'total_price']

       

    def create(self, validated_data):
        
        order_items_data = validated_data.pop('order_items', []) #order item data same as attrs.
        
        order = Order.objects.create(**validated_data) #order created
              
        
        for item in order_items_data:            
            item['order'] = order  # Link order
        self.fields['order_items'].create(order_items_data)  

                     
        
        # Collect unique companies from the order items
        companies = {item_data['product'].company for item_data in order_items_data}
        

        # Bulk create OrderCompanyStatus entries
        order_company_status_entries = [
            OrderCompanyStatus(
                order=order,
                company=company,
                status='pending',
                last_updated=timezone.now()
            )
            for company in companies
        ]
        

        OrderCompanyStatus.objects.bulk_create(order_company_status_entries)

        # Calculate total price
        order.calculate_total_price()

        return order



    def update(self, instance, validated_data):
        order_items_data = validated_data.pop('order_items', [])
        
        # Update the Order instance
        instance = super().update(instance, validated_data)

        # Use the custom list serializer to handle bulk updates
        
        self.fields['order_items'].update(instance.order_items.all(), order_items_data)
        
        # Recalculate total price
        instance.calculate_total_price()
        return instance

     

    
class OrderCompanyStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderCompanyStatus
        fields = ['order','company', 'status', 'last_updated']

    
class AdminOrderItemSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = OrderItem
        fields = [ 'product', 'quantity']



class AdminOrderSerializer(serializers.ModelSerializer):
    order_items = AdminOrderItemSerializer(many=True)
    filtered_total_price = serializers.SerializerMethodField()
    statuses = OrderCompanyStatusSerializer(source='ordercompanystatus_set', many=True, read_only=True)


    class Meta:
        model = Order
        fields = ['id', 'user', 'order_items', 'date_ordered', 'location', 'time_of_delivery', 'filtered_total_price','statuses']
        read_only_fields = ['user', 'date_ordered']

    def get_filtered_total_price(self, instance):
        """
        Calculate the total price based on filtered order items belonging to the admin's company.
        """
        request = self.context.get('request')
        user = request.user

        # Filter the order items to include only those with products from the admin's company
        filtered_items = [
            item for item in instance.order_items.all()
            if item.product.company == user.company
        ]
        
        # Calculate the total price of filtered items
        total_price = sum(item.amount for item in filtered_items)

        return total_price

    def to_representation(self, instance):
        """
        Customize representation to include only order items belonging to the admin's company.
        """
        representation = super().to_representation(instance)
        request = self.context.get('request')
        user = request.user

        # Filter order items to include only those with products belonging to the admin's company
        filtered_items = [
            item_data for item_data in representation['order_items']
            if Product.objects.filter(id=item_data['product'], company=user.company).exists()
        ]
        
        # Update the order_items field in the representation
        representation['order_items'] = filtered_items

        return representation
    
class CartItemSerializer(serializers.ModelSerializer):
    

    class Meta:
        model = CartItem
        fields = ['id', 'product', 'quantity', 'total_price']
        read_only_fields = ['total_price']

class CartSerializer(serializers.ModelSerializer):
    
    cart_items = CartItemSerializer(many=True, read_only=True)
    # total_price = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = ['id', 'user', 'created_at', 'cart_items']

    # def get_total_price(self, obj):
    #     return obj.get_total_price()



class InvitationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=[('admin', 'Admin'), ('staff', 'Staff')])   



#---------------------ListSerializer------------------------------





    


