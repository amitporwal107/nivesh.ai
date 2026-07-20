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
public final class GoalsRepository_Factory implements Factory<GoalsRepository> {
  private final Provider<NiveshApi> apiProvider;

  public GoalsRepository_Factory(Provider<NiveshApi> apiProvider) {
    this.apiProvider = apiProvider;
  }

  @Override
  public GoalsRepository get() {
    return newInstance(apiProvider.get());
  }

  public static GoalsRepository_Factory create(Provider<NiveshApi> apiProvider) {
    return new GoalsRepository_Factory(apiProvider);
  }

  public static GoalsRepository newInstance(NiveshApi api) {
    return new GoalsRepository(api);
  }
}
