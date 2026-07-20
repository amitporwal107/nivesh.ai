package ai.nivesh.app.ui.tax;

import ai.nivesh.app.data.repo.DashboardsRepository;
import dagger.internal.DaggerGenerated;
import dagger.internal.Factory;
import dagger.internal.QualifierMetadata;
import dagger.internal.ScopeMetadata;
import javax.annotation.processing.Generated;
import javax.inject.Provider;

@ScopeMetadata
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
public final class TaxViewModel_Factory implements Factory<TaxViewModel> {
  private final Provider<DashboardsRepository> dashboardsProvider;

  public TaxViewModel_Factory(Provider<DashboardsRepository> dashboardsProvider) {
    this.dashboardsProvider = dashboardsProvider;
  }

  @Override
  public TaxViewModel get() {
    return newInstance(dashboardsProvider.get());
  }

  public static TaxViewModel_Factory create(Provider<DashboardsRepository> dashboardsProvider) {
    return new TaxViewModel_Factory(dashboardsProvider);
  }

  public static TaxViewModel newInstance(DashboardsRepository dashboards) {
    return new TaxViewModel(dashboards);
  }
}
