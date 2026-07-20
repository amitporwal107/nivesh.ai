package ai.nivesh.app.data.repo;

import ai.nivesh.app.data.api.NiveshApi;
import dagger.internal.DaggerGenerated;
import dagger.internal.Factory;
import dagger.internal.QualifierMetadata;
import dagger.internal.ScopeMetadata;
import javax.annotation.processing.Generated;
import javax.inject.Provider;

@ScopeMetadata("javax.inject.Singleton")
@QualifierMetadata
@DaggerGenerated
@Generated(
    value = "dagger.internal.codegen.ComponentProcessor",
    comments = "https://dagger.dev"
)
@SuppressWarnings({
    "unchecked",
    "rawtypes",
    "KotlinInternal",
    "KotlinInternalInJava"
})
public final class DashboardsRepository_Factory implements Factory<DashboardsRepository> {
  private final Provider<NiveshApi> apiProvider;

  public DashboardsRepository_Factory(Provider<NiveshApi> apiProvider) {
    this.apiProvider = apiProvider;
  }

  @Override
  public DashboardsRepository get() {
    return newInstance(apiProvider.get());
  }

  public static DashboardsRepository_Factory create(Provider<NiveshApi> apiProvider) {
    return new DashboardsRepository_Factory(apiProvider);
  }

  public static DashboardsRepository newInstance(NiveshApi api) {
    return new DashboardsRepository(api);
  }
}
