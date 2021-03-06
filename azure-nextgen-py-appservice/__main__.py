import pulumi_azure_nextgen.insights.latest as insights
import pulumi_azure_nextgen.resources.latest as resource
import pulumi_azure_nextgen.sql.latest as sql
import pulumi_azure_nextgen.storage.latest as storage
import pulumi_azure_nextgen.web.latest as web
from pulumi import Config, Output, asset, export
from pulumi_azure_nextgen.storage.latest import (BlobContainer, PublicAccess,
                                                 StorageAccount)

username = "pulumi"

config = Config()
pwd = config.require("sqlPassword")

resource_group = resource.ResourceGroup("appservicerg",
                                        resource_group_name="appservicerg",
                                        location="westus2")

storage_account = storage.StorageAccount(
    "appservicesa",
    account_name="appservicesa",
    resource_group_name=resource_group.name,
    kind="StorageV2",
    sku=storage.SkuArgs(name=storage.SkuName.STANDARD_LRS))

app_service_plan = web.AppServicePlan(
    "appservice-asp",
    name="appservice-asp",
    resource_group_name=resource_group.name,
    kind="App",
    sku=web.SkuDescriptionArgs(
        tier="Basic",
        name="B1",
    ))

storage_container = BlobContainer(
    "appservice-c",
    container_name="appservice-c",
    account_name=storage_account.name,
    public_access=PublicAccess.NONE,
    resource_group_name=resource_group.name)

blob = storage.Blob(
    "appservice-b",
    blob_name="appservice-b",
    resource_group_name=resource_group.name,
    account_name=storage_account.name,
    container_name=storage_container.name,
    type="Block",
    source=asset.FileArchive("wwwroot"))


def get_sas(args):
    blob_sas = storage.list_storage_account_service_sas(
        account_name=storage_account.name,
        protocols=storage.HttpProtocol.HTTPS,
        shared_access_start_time="2021-01-01",
        shared_access_expiry_time="2030-01-01",
        resource=storage.SignedResource.C,
        resource_group_name=args[3],
        permissions=storage.Permissions.R,
        canonicalized_resource="/blob/" + args[0] + "/" + args[1],
        content_type="application/json",
        cache_control="max-age=5",
        content_disposition="inline",
        content_encoding="deflate",
    )
    return f"https://{args[0]}.blob.core.windows.net/{args[1]}/{args[2]}?{blob_sas.service_sas_token}"

signed_blob_url = Output.all(
    storage_account.name,
    storage_container.name,
    blob.name,
    resource_group.name,
).apply(get_sas)

app_insights = insights.Component(
    "appservice-ai",
    resource_name_="appservice-ai",
    kind="web",
    resource_group_name=resource_group.name,
    location=resource_group.location,
    application_type=insights.ApplicationType.WEB)

sql_server = sql.Server(
    "appservice-sql",
    server_name="appservice-sql",
    resource_group_name=resource_group.name,
    location=resource_group.location,
    administrator_login=username,
    administrator_login_password=pwd,
    version="12.0")

database = sql.Database(
    "appservice-db",
    database_name="appservice-db",
    resource_group_name=resource_group.name,
    location=resource_group.location,
    server_name=sql_server.name,
    requested_service_objective_name=sql.ServiceObjectiveName.S0)

connection_string = Output.all(sql_server.name, database.name, username, pwd) \
    .apply(lambda args: f"Server=tcp:{args[0]}.database.windows.net;initial catalog={args[1]};user ID={args[2]};password={args[3]};Min Pool Size=0;Max Pool Size=30;Persist Security Info=true;")

app = web.WebApp(
    "appservice-as",
    name="appserviceas123",
    resource_group_name=resource_group.name,
    location=resource_group.location,
    server_farm_id=app_service_plan.id,
    site_config=web.SiteConfigArgs(
        app_settings=[web.NameValuePairArgs(name="APPINSIGHTS_INSTRUMENTATIONKEY", value=app_insights.instrumentation_key),
             web.NameValuePairArgs(name="APPLICATIONINSIGHTS_CONNECTION_STRING", value=app_insights.instrumentation_key.apply(
                 lambda key: "InstrumentationKey=" + key
             )),
             web.NameValuePairArgs(name="ApplicationInsightsAgent_EXTENSION_VERSION", value="~2"),
             web.NameValuePairArgs(name="WEBSITE_RUN_FROM_PACKAGE", value=signed_blob_url)],
        connection_strings=[web.ConnStringInfoArgs(
            name="db",
            type="SQLAzure",
            connection_string=connection_string,
        )]
    )
)

export("endpoint", app.default_host_name.apply(
    lambda endpoint: "https://" + endpoint
))
