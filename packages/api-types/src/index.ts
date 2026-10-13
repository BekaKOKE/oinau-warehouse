/**
 * Типы API.
 *
 * schema.d.ts ГЕНЕРИРУЕТСЯ из OpenAPI командой `make gen-types`.
 * Руками его не правят: единственный источник истины — схемы Pydantic
 * в backend.
 *
 * Ниже — только удобные псевдонимы для публичной поверхности API.
 * FastAPI разводит одноимённые схемы публичного API и админки по полным
 * путям модулей (`app__modules__catalog__schemas__PriceTierRead`), и имя
 * меняется, когда одноимённая схема появляется или исчезает. Компоненты
 * витрины поэтому импортируют только псевдонимы отсюда — при таком
 * переименовании правится одна строка, а не экраны.
 */

import type { components } from './schema';

export type { paths, components, operations } from './schema';

type Schemas = components['schemas'];

export type ApiErrorBody = {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
    request_id?: string;
  };
};

export type HealthResponse = Schemas['HealthResponse'];

// ------------------------------------------------------------- каталог

export type CategoryNode = Schemas['CategoryNode'];
export type CategoryDetail = Schemas['CategoryDetail'];
export type CategoryBreadcrumb = Schemas['CategoryBreadcrumb'];

export type PricingType = Schemas['PricingType'];
export type PriceTier = Schemas['app__modules__catalog__schemas__PriceTierRead'];
export type PriceInfo = Schemas['PriceInfo'];
export type PublicAvailability = Schemas['PublicAvailability'];
export type ProductImage = Schemas['ImageRead'];
export type ProductCharacteristic = Schemas['CharacteristicRead'];
export type ProductDocument = Schemas['DocumentRead'];
export type CategoryFacet = Schemas['FacetRead'];
export type CategoryFacetOption = Schemas['FacetOptionRead'];

export type ProductListItem = Schemas['ProductListItem'];
export type ProductDetail = Schemas['ProductDetail'];
export type ProductColorOption = Schemas['ProductColorOption'];
export type ProductColorDetail = Schemas['ProductColorDetail'];
export type ProductPage = Schemas['Page_ProductListItem_'];
export type ProductSort = Schemas['ProductSort'];

// -------------------------------------------------------------- заявки

export type RequestItemInput = Schemas['PublicRequestItemInput'];
export type RequestCreate = Schemas['PublicRequestCreate'];
export type RequestCreated = Schemas['PublicRequestCreated'];
export type RequestCreatedItem = Schemas['PublicRequestItemRead'];
export type RequestSource = Schemas['RequestSource'];

// Быстрый заказ: тело — multipart/form-data, поэтому схемы запроса
// в OpenAPI нет; поля совпадают с PublicQuickRequestCreate на backend.
export type QuickRequestMode = Schemas['QuickRequestMode'];
export type QuickRequestCreated = Schemas['PublicQuickRequestCreated'];
export type QuickRequestBelowMinimum = Schemas['QuickRequestBelowMinimum'];

// ----------------------------------------------------------------- CMS

export type SiteSettings = Schemas['PublicSiteSettings'];
export type HomeContent = Schemas['PublicHome'];
export type ContactsContent = Schemas['PublicContacts'];
export type DeliveryContent = Schemas['PublicDelivery'];
export type FaqContent = Schemas['PublicFaq'];
export type ServicesContent = Schemas['PublicServices'];
export type ServiceItem = Schemas['PublicService'];
export type Seo = Schemas['PublicSeo'];
export type ContentImage = Schemas['PublicImage'];

// ------------------------------------------------------------ регионы

export type Region = Schemas['RegionRead'];

// ------------------------------------------------------- кабинет клиента

export type CustomerRegister = Schemas['CustomerRegister'];
export type CustomerLogin = Schemas['CustomerLogin'];
export type CustomerTokenResponse = Schemas['CustomerTokenResponse'];
export type AcceptedResponse = Schemas['AcceptedResponse'];
export type PasswordResetConfirm = Schemas['PasswordResetConfirm'];

export type RegionRef = Schemas['RegionRef'];
export type CustomerProfile = Schemas['CustomerProfileRead'];
export type CustomerProfileUpdate = Schemas['CustomerProfileUpdate'];

export type CustomerFavorite = Schemas['FavoriteRead'];
export type CustomerFavoritePage = Schemas['Page_FavoriteRead_'];

export type CustomerRequestStatus = Schemas['CustomerRequestStatus'];
export type CustomerRequestCreate = Schemas['CustomerRequestCreate'];
export type CustomerRequestListItem = Schemas['CustomerRequestListItem'];
export type CustomerRequestPage = Schemas['Page_CustomerRequestListItem_'];
export type CustomerRequestDetail = Schemas['CustomerRequestDetail'];
export type CustomerRequestItem = Schemas['CustomerRequestItemRead'];
export type CustomerRequestComment = Schemas['CustomerRequestCommentRead'];

export type ProjectStatus = Schemas['ProjectStatus'];
export type ProjectCreate = Schemas['ProjectCreate'];
export type ProjectUpdate = Schemas['ProjectUpdate'];
export type ProjectItemAdd = Schemas['ProjectItemAdd'];
export type ProjectItem = Schemas['ProjectItemRead'];
export type ProjectRequestRef = Schemas['ProjectRequestRef'];
export type ProjectListItem = Schemas['ProjectListItem'];
export type ProjectPage = Schemas['Page_ProjectListItem_'];
export type ProjectDetail = Schemas['ProjectDetail'];

export type NotificationType = Schemas['NotificationType'];
export type CustomerNotification = Schemas['NotificationRead'];
export type NotificationPage = Schemas['Page_NotificationRead_'];
export type UnreadCount = Schemas['UnreadCount'];
